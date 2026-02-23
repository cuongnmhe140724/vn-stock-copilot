"""LangGraph node functions for the stock analysis pipeline.

Three nodes:
  1. researcher_node  – fetches raw data from vnstock + news
  2. analyst_node     – sends data to Claude for structured analysis
  3. strategist_node  – produces final strategy & Telegram-ready message
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from config import get_settings
from models.state import AgentState, FinancialAnalysis, TechnicalSignals, InvestmentStrategy
from services import vnstock_service, news_service
from database import crud
from prompts.system_prompts import ANALYSIS_SYSTEM_PROMPT, ANALYST_PROMPT

logger = logging.getLogger(__name__)


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

    return {
        "current_price": current_price,
        "raw_financials": raw_financials,
        "raw_ohlc": raw_ohlc,
        "raw_news": raw_news,
        "previous_thesis": previous_thesis,
    }


# ─────────────────────────────────────────────────────────────────────────────
# NODE 2: Analyst — structured analysis via Claude
# ─────────────────────────────────────────────────────────────────────────────


def analyst_node(state: AgentState) -> dict[str, Any]:
    """Send raw data to Claude and parse structured FA/TA analysis."""

    ticker = state["ticker"]
    logger.info("📊 Analyst: analysing %s with Claude", ticker)

    llm = _get_llm()

    # Build data context for the LLM
    data_context = (
        f"## Dữ liệu tài chính cho {ticker}\n\n"
        f"### Financial Ratios\n```json\n{json.dumps(state['raw_financials'], default=str, ensure_ascii=False, indent=2)}\n```\n\n"
        f"### Price & Technical Data\n```json\n{json.dumps(state['raw_ohlc'], default=str, ensure_ascii=False, indent=2)}\n```\n\n"
        f"### Tin tức gần đây\n" + "\n".join(f"- {n}" for n in state.get("raw_news", []))
    )

    messages = [
        SystemMessage(content=ANALYST_PROMPT),
        HumanMessage(content=data_context),
    ]

    try:
        response = llm.invoke(messages)
        content = response.content.strip()

        # Try to parse JSON from response
        # Handle markdown code blocks
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        parsed = json.loads(content)

        fa_data = parsed.get("financial_analysis", {})
        ta_data = parsed.get("technical_signals", {})

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

        return {
            "financial_analysis": financial_analysis,
            "technical_signals": technical_signals,
        }

    except Exception as exc:
        logger.exception("Analyst node failed for %s: %s", ticker, exc)
        return {
            "financial_analysis": None,
            "technical_signals": None,
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

    fa_summary = ""
    if fa:
        fa_summary = (
            f"Revenue Growth: {fa.revenue_growth}% | Profit Growth: {fa.profit_growth}%\n"
            f"ROE: {fa.roe}% | P/E: {fa.pe_ratio} | D/E: {fa.debt_to_equity}\n"
            f"Sức khỏe tài chính: {'✅ Tốt' if fa.is_healthy else '⚠️ Cần lưu ý'}"
        )

    ta_summary = ""
    if ta:
        ta_summary = (
            f"Xu hướng: {ta.trend} | RSI: {ta.rsi}\n"
            f"MA: {ta.ma_alignment}\n"
            f"Hỗ trợ: {ta.support_zone} | Kháng cự: {ta.resistance_zone}"
        )

    previous = state.get("previous_thesis") or "Chưa có luận điểm trước đó."
    news_text = "\n".join(f"- {n}" for n in state.get("raw_news", []))

    context = (
        f"# Phân tích mã {ticker}\n\n"
        f"**Giá hiện tại**: {state.get('current_price', 0):,.0f} VNĐ\n\n"
        f"## Fundamental Analysis\n{fa_summary}\n\n"
        f"## Technical Analysis\n{ta_summary}\n\n"
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

        return {
            "current_strategy": strategy,
            "final_message": final_message,
        }

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
        current_price = state.get("current_price", 0)

        # Estimate entry zone around -5% to current price
        entry_low = current_price * 0.92
        entry_high = current_price * 0.98

        # Estimate target +20%
        target = current_price * 1.20

        # Stop-loss at -10%
        stop = current_price * 0.90

        # Risk level
        risk = "MEDIUM"
        if fa and fa.is_healthy and ta and ta.trend == "UP":
            risk = "LOW"
        elif ta and ta.trend == "DOWN":
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
