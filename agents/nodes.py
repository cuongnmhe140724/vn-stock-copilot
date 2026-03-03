"""LangGraph node functions for the stock analysis pipeline.

Three nodes:
  1. researcher_node  – fetches raw data from vnstock + news
  2. analyst_node     – ReAct agent with SMC/Elliott/Wyckoff tools + structured analysis
  3. strategist_node  – produces final strategy & Telegram-ready message
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from config import get_settings
from models.state import AgentState, FinancialAnalysis, TechnicalSignals, InvestmentStrategy
from services import vnstock_service, news_service
from database import crud
from prompts.system_prompts import ANALYSIS_SYSTEM_PROMPT, ANALYST_PROMPT
from agents.tools import ANALYST_TOOLS

logger = logging.getLogger(__name__)


def _safe_json_dumps(obj: Any) -> str:
    """JSON serialize with full safety for pandas/numpy types."""
    return json.dumps(_sanitize(obj), default=str, ensure_ascii=False, indent=2)


def _sanitize(obj: Any) -> Any:
    """Recursively make any object JSON-serializable.

    Handles: tuple dict keys, numpy scalars, pandas Timestamps,
    NaN/Inf, bytes, sets, and any other non-JSON-native type.
    """
    import numpy as np
    import pandas as pd

    # Dict – convert keys to str, recurse values
    if isinstance(obj, dict):
        return {str(k): _sanitize(v) for k, v in obj.items()}

    # List / tuple / set
    if isinstance(obj, (list, tuple, set)):
        return [_sanitize(item) for item in obj]

    # Pandas Timestamp
    if isinstance(obj, (pd.Timestamp,)):
        return obj.isoformat()

    # Numpy scalar types
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        if np.isnan(v) or np.isinf(v):
            return None
        return v
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.ndarray,)):
        return _sanitize(obj.tolist())

    # Python float NaN/Inf
    if isinstance(obj, float):
        if obj != obj or obj == float("inf") or obj == float("-inf"):
            return None

    # Pydantic models
    if hasattr(obj, "model_dump"):
        return _sanitize(obj.model_dump())

    # bytes
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")

    return obj


# Keep backward compat alias
_sanitize_keys = _sanitize


def _g(obj: Any, key: str, default: Any = None) -> Any:
    """Get a value from a dict or object attribute — works with both."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _get_llm() -> ChatAnthropic:
    """Return a configured Claude LLM instance."""
    settings = get_settings()
    return ChatAnthropic(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key,
        max_tokens=4096,
        temperature=0.3,
    )


# ─────────────────────────────────────────────────────────────────────────────
# NODE 1: Researcher — gather raw data
# ─────────────────────────────────────────────────────────────────────────────


def researcher_node(state: AgentState) -> dict[str, Any]:
    """Fetch financial ratios, price history, and news for the ticker."""

    ticker = state["ticker"]
    logger.info("🔍 Researcher: fetching data for %s", ticker)

    # Financial data
    raw_financials = vnstock_service.get_financial_ratios(ticker)

    # Price data (OHLCV)
    price_df = vnstock_service.get_price_history(ticker, days=365)
    if isinstance(price_df, dict):
        raw_ohlc = price_df  # error dict
        current_price = 0.0
    else:
        # Calculate technical indicators
        tech = vnstock_service.calculate_technical_indicators(price_df)
        raw_ohlc = {
            "latest_data": price_df.tail(5).to_dict(orient="records"),
            "technical": tech,
            "total_rows": len(price_df),
        }
        current_price = tech.get("latest_close", 0.0)

    # News
    raw_news = news_service.search_news_sync(ticker, limit=5)

    # Previous thesis from DB (for comparison)
    previous_thesis = None
    try:
        thesis = crud.get_latest_thesis(ticker)
        if thesis:
            previous_thesis = thesis.get("thesis_content", "")
    except Exception:
        logger.warning("Could not fetch previous thesis from DB")

    return _sanitize_keys({
        "current_price": current_price,
        "raw_financials": raw_financials,
        "raw_ohlc": raw_ohlc,
        "raw_news": raw_news,
        "previous_thesis": previous_thesis,
    })


# ─────────────────────────────────────────────────────────────────────────────
# NODE 2: Analyst — ReAct agent with SMC/Elliott/Wyckoff tools
# ─────────────────────────────────────────────────────────────────────────────


def analyst_node(state: AgentState) -> dict[str, Any]:
    """Run a ReAct agent that calls SMC, Elliott Wave, and Wyckoff tools,
    then synthesises structured FA/TA analysis as JSON."""

    ticker = state["ticker"]
    logger.info("📊 Analyst: analysing %s with ReAct agent (3 tools)", ticker)

    llm = _get_llm()

    # Build data context for the agent
    data_context = (
        f"## Dữ liệu tài chính cho {ticker}\n\n"
        f"### Financial Ratios\n```json\n{_safe_json_dumps(state['raw_financials'])}\n```\n\n"
        f"### Price & Technical Data\n```json\n{_safe_json_dumps(state['raw_ohlc'])}\n```\n\n"
        f"### Tin tức gần đây\n" + "\n".join(f"- {n}" for n in state.get("raw_news", []))
        + f"\n\n**Mã chứng khoán cần phân tích: {ticker}**"
    )

    try:
        # Create a ReAct sub-agent with the 3 TA tools
        react_agent = create_react_agent(
            model=llm,
            tools=ANALYST_TOOLS,
            prompt=ANALYST_PROMPT,
        )

        # Invoke the ReAct agent
        agent_result = react_agent.invoke(
            {"messages": [HumanMessage(content=data_context)]}
        )

        # Extract the final message from agent output
        final_msg = agent_result["messages"][-1]
        content = final_msg.content if hasattr(final_msg, "content") else str(final_msg)
        content = content.strip()

        # Parse JSON from response (handle markdown code blocks)
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        parsed = json.loads(content)

        # Extract structured data
        fa_data = parsed.get("financial_analysis", {})
        ta_data = parsed.get("technical_signals", {})
        smc_data = parsed.get("smc_analysis")
        elliott_data = parsed.get("elliott_analysis")
        wyckoff_data = parsed.get("wyckoff_analysis")

        financial_analysis = FinancialAnalysis(
            revenue_growth=fa_data.get("revenue_growth", 0),
            profit_growth=fa_data.get("profit_growth", 0),
            roe=fa_data.get("roe", 0),
            pe_ratio=fa_data.get("pe_ratio", 0),
            debt_to_equity=fa_data.get("debt_to_equity", 0),
            is_healthy=fa_data.get("is_healthy", False),
        )

        technical_signals = TechnicalSignals(
            trend=ta_data.get("trend", "SIDEWAYS"),
            rsi=ta_data.get("rsi", 50),
            ma_alignment=ta_data.get("ma_alignment", "N/A"),
            support_zone=ta_data.get("support_zone", "N/A"),
            resistance_zone=ta_data.get("resistance_zone", "N/A"),
        )

        return _sanitize({
            "financial_analysis": financial_analysis,
            "technical_signals": technical_signals,
            "smc_analysis": smc_data,
            "elliott_analysis": elliott_data,
            "wyckoff_analysis": wyckoff_data,
        })

    except json.JSONDecodeError as exc:
        logger.warning(
            "Analyst agent returned non-JSON for %s, falling back to raw text: %s",
            ticker, exc,
        )
        # Fallback: still try to return what we got from the agent
        return _sanitize({
            "financial_analysis": None,
            "technical_signals": None,
            "smc_analysis": None,
            "elliott_analysis": None,
            "wyckoff_analysis": None,
        })

    except Exception as exc:
        logger.exception("Analyst node failed for %s: %s", ticker, exc)
        return {
            "financial_analysis": None,
            "technical_signals": None,
            "smc_analysis": None,
            "elliott_analysis": None,
            "wyckoff_analysis": None,
        }


# ─────────────────────────────────────────────────────────────────────────────
# NODE 3: Strategist — final strategy & Telegram message
# ─────────────────────────────────────────────────────────────────────────────


def strategist_node(state: AgentState) -> dict[str, Any]:
    """Produce final investment strategy and a formatted Markdown report."""

    ticker = state["ticker"]
    logger.info("🎯 Strategist: building strategy for %s", ticker)

    llm = _get_llm()

    # Build context from all previous analysis
    fa = state.get("financial_analysis")
    ta = state.get("technical_signals")
    smc = state.get("smc_analysis")
    elliott = state.get("elliott_analysis")
    wyckoff = state.get("wyckoff_analysis")

    fa_summary = ""
    if fa:
        fa_summary = (
            f"Revenue Growth: {_g(fa, 'revenue_growth')}% | Profit Growth: {_g(fa, 'profit_growth')}%\n"
            f"ROE: {_g(fa, 'roe')}% | P/E: {_g(fa, 'pe_ratio')} | D/E: {_g(fa, 'debt_to_equity')}\n"
            f"Sức khỏe tài chính: {'✅ Tốt' if _g(fa, 'is_healthy') else '⚠️ Cần lưu ý'}"
        )

    ta_summary = ""
    if ta:
        ta_summary = (
            f"Xu hướng: {_g(ta, 'trend')} | RSI: {_g(ta, 'rsi')}\n"
            f"MA: {_g(ta, 'ma_alignment')}\n"
            f"Hỗ trợ: {_g(ta, 'support_zone')} | Kháng cự: {_g(ta, 'resistance_zone')}"
        )

    # SMC summary
    smc_summary = ""
    if smc:
        smc_summary = (
            f"Xu hướng SMC: {smc.get('current_trend', 'N/A')}\n"
            f"CHoCH gần nhất: {_safe_json_dumps(smc.get('recent_choch'))}\n"
            f"Bullish OB: {_safe_json_dumps(smc.get('active_bullish_order_blocks', []))}\n"
            f"Bearish OB: {_safe_json_dumps(smc.get('active_bearish_order_blocks', []))}\n"
            f"FVG chưa lấp: {_safe_json_dumps(smc.get('unfilled_fvg', []))}"
        )

    # Elliott summary
    elliott_summary = ""
    if elliott:
        elliott_summary = (
            f"Cấu trúc: {elliott.get('primary_structure', 'N/A')}\n"
            f"Sóng hiện tại: {elliott.get('current_wave_label', 'N/A')}\n"
            f"Mục tiêu Fibonacci: {_safe_json_dumps(elliott.get('target_fibonacci_zones', []))}\n"
            f"Invalidation: {elliott.get('invalidation_level', 'N/A')}"
        )

    # Wyckoff summary
    wyckoff_summary = ""
    if wyckoff:
        wyckoff_summary = (
            f"Giai đoạn: {wyckoff.get('phase', 'N/A')}\n"
            f"POC: {_safe_json_dumps(wyckoff.get('point_of_control'))}\n"
            f"Value Area: {_safe_json_dumps(wyckoff.get('value_area'))}\n"
            f"Trading Range: {_safe_json_dumps(wyckoff.get('trading_range'))}"
        )

    previous = state.get("previous_thesis") or "Chưa có luận điểm trước đó."
    news_text = "\n".join(f"- {n}" for n in state.get("raw_news", []))

    context = (
        f"# Phân tích mã {ticker}\n\n"
        f"**Giá hiện tại**: {state.get('current_price', 0):,.0f} VNĐ\n\n"
        f"## Fundamental Analysis\n{fa_summary}\n\n"
        f"## Technical Analysis (Classic)\n{ta_summary}\n\n"
        f"## Smart Money Concepts (SMC)\n{smc_summary}\n\n"
        f"## Elliott Wave\n{elliott_summary}\n\n"
        f"## Wyckoff Analysis\n{wyckoff_summary}\n\n"
        f"## Tin tức\n{news_text}\n\n"
        f"## Luận điểm đầu tư trước đó\n{previous}\n"
    )

    messages = [
        SystemMessage(content=ANALYSIS_SYSTEM_PROMPT),
        HumanMessage(content=context),
    ]

    try:
        response = llm.invoke(messages)
        final_message = response.content.strip()

        # Try to extract strategy parameters from the report
        strategy = _extract_strategy_from_report(final_message, state)

        # Save thesis to database
        try:
            if strategy:
                crud.upsert_thesis(
                    symbol=ticker,
                    thesis_content=final_message,
                    target_price=strategy.target_price,
                    stop_loss_price=strategy.stop_loss,
                    entry_zone_min=strategy.entry_price_range[0] if strategy.entry_price_range else 0,
                    entry_zone_max=strategy.entry_price_range[1] if len(strategy.entry_price_range) > 1 else 0,
                )
            else:
                crud.upsert_thesis(symbol=ticker, thesis_content=final_message)
        except Exception:
            logger.warning("Could not save thesis to DB (DB might not be configured)")

        return _sanitize({
            "current_strategy": strategy,
            "final_message": final_message,
        })

    except Exception as exc:
        logger.exception("Strategist node failed for %s: %s", ticker, exc)
        return {
            "current_strategy": None,
            "final_message": f"❌ Lỗi khi phân tích {ticker}: {exc}",
        }


def _extract_strategy_from_report(
    report: str, state: AgentState
) -> InvestmentStrategy | None:
    """Best-effort extraction of strategy parameters from the Markdown report."""
    try:
        # Defaults
        thesis_summary = report[:200] if report else ""

        fa = state.get("financial_analysis")
        ta = state.get("technical_signals")
        smc = state.get("smc_analysis")
        elliott = state.get("elliott_analysis")
        current_price = state.get("current_price", 0)

        # Try to use Order Block zones for entry if available
        entry_low = current_price * 0.92
        entry_high = current_price * 0.98

        if smc:
            bullish_obs = smc.get("active_bullish_order_blocks", [])
            if bullish_obs:
                # Use the nearest bullish OB as entry zone
                nearest_ob = bullish_obs[-1] if bullish_obs else None
                if nearest_ob and isinstance(nearest_ob, dict):
                    ob_bottom = nearest_ob.get("bottom", 0)
                    ob_top = nearest_ob.get("top", 0)
                    if ob_bottom > 0 and ob_top > 0:
                        entry_low = ob_bottom
                        entry_high = ob_top

        # Try to use Fibonacci targets if available
        target = current_price * 1.20
        if elliott:
            fib_targets = elliott.get("target_fibonacci_zones", [])
            if fib_targets and isinstance(fib_targets, list):
                for ft in fib_targets:
                    if isinstance(ft, dict):
                        t_price = ft.get("price", 0)
                        if t_price > current_price:
                            target = t_price
                            break

        # Stop-loss: use invalidation level if available, else -10%
        stop = current_price * 0.90
        if elliott:
            inv = elliott.get("invalidation_level")
            if inv and isinstance(inv, (int, float)) and inv > 0:
                stop = inv

        # Risk level
        risk = "MEDIUM"
        if fa and _g(fa, 'is_healthy') and ta and _g(ta, 'trend') == "UP":
            risk = "LOW"
        elif ta and _g(ta, 'trend') == "DOWN":
            risk = "HIGH"

        return InvestmentStrategy(
            thesis_summary=thesis_summary,
            entry_price_range=[round(entry_low, 0), round(entry_high, 0)],
            target_price=round(target, 0),
            stop_loss=round(stop, 0),
            risk_level=risk,
        )
    except Exception:
        return None
