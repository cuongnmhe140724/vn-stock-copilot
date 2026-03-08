"""Backtrader Strategy that delegates buy/sell decisions to the real agent pipeline.

Both ``signal_mode`` and ``agent_mode`` run the **same** 3-step pipeline
(researcher → analyst → strategist) — only the LLM backend differs:

* **agent_mode** → Claude (Anthropic)
* **signal_mode** → DeepSeek R1 (OpenAI-compatible)

The pipeline code lives in ``agents/nodes.py`` and is shared 1:1 with the
live system.  The only difference is that ``vnstock_service`` is monkey-patched
to ``VnstockBacktestService`` so data comes from the ``LookbackProvider``
instead of the live API.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import backtrader as bt

from backtesting.lookback_provider import LookbackProvider
from services.vnstock_backtest_service import VnstockBacktestService

logger = logging.getLogger(__name__)


# ── Signal constants ─────────────────────────────────────────────────────────

SIGNAL_BUY = "BUY"
SIGNAL_SELL = "SELL"
SIGNAL_HOLD = "HOLD"


class AgentStrategy(bt.Strategy):
    """Backtrader Strategy powered by the shared AI pipeline.

    Parameters
    ----------
    lookback_provider : LookbackProvider
        Point-in-time data source (anti-look-ahead).
    ticker : str
        Stock ticker symbol (e.g. "FPT").
    mode : str
        ``"signal_mode"`` (DeepSeek R1) or ``"agent_mode"`` (Claude).
        Both run the same pipeline, only the LLM differs.
    rebalance_every : int
        Run the agent every N bars (default: 2).
    position_size_pct : float
        Fraction of portfolio to allocate per trade (default: 0.9 = 90%).
    max_bars : int
        Stop after N bars (0 = run all).
    """

    params = (
        ("lookback_provider", None),
        ("ticker", ""),
        ("mode", "signal_mode"),
        ("rebalance_every", 2),
        ("position_size_pct", 0.9),
        ("max_bars", 0),
    )

    def __init__(self):
        self.trade_log: list[dict] = []
        self._bar_count = 0
        self._last_signal: str = SIGNAL_HOLD
        self._last_reasoning: str = ""
        self.stopped_early: bool = False

    # ------------------------------------------------------------------
    # Backtrader lifecycle
    # ------------------------------------------------------------------

    def next(self):
        """Called on every bar — delegates to the shared AI pipeline."""
        bar_idx = len(self) - 1
        self._bar_count += 1

        # Early stop: close position and halt engine
        if self.p.max_bars > 0 and self._bar_count >= self.p.max_bars:
            if self.position:
                self.close()
                logger.info("⏹️  Early stop at bar %d — closing open position", bar_idx)
            self.stopped_early = True
            self.env.runstop()
            return

        # Advance the data cutoff to this bar
        if self.p.lookback_provider is not None:
            self.p.lookback_provider.advance(bar_idx)

        # Only run agent every N bars
        if bar_idx % self.p.rebalance_every != 0:
            return

        current_date = self.data.datetime.date(0).isoformat()
        current_price = self.data.close[0]

        logger.info(
            "📊 Bar %d (%s) — price=%.0f — running %s",
            bar_idx, current_date, current_price, self.p.mode,
        )

        try:
            result = self._run_pipeline()
            signal = result.get("signal", SIGNAL_HOLD).upper()
            reasoning = result.get("reasoning", "")
            self._last_signal = signal
            self._last_reasoning = reasoning
            self._execute_signal(signal, result, current_date, current_price)

        except Exception as exc:
            logger.exception("Strategy error at bar %d: %s", bar_idx, exc)

    def stop(self):
        """Called when backtest finishes."""
        logger.info(
            "🏁 Backtest finished — %d trades recorded, final portfolio: %.0f",
            len(self.trade_log), self.broker.getvalue(),
        )

    def notify_trade(self, trade):
        """Log completed trades."""
        if trade.isclosed:
            self.trade_log.append({
                "date": self.data.datetime.date(0).isoformat(),
                "ticker": self.p.ticker,
                "pnl": round(trade.pnl, 0),
                "pnl_pct": round(trade.pnlcomm / abs(trade.price * trade.size) * 100, 2)
                    if trade.price and trade.size else 0,
                "size": trade.size,
                "price": round(trade.price, 0),
                "bar_length": trade.barlen,
            })

    # ------------------------------------------------------------------
    # Shared pipeline — identical to live agent
    # ------------------------------------------------------------------

    def _run_pipeline(self) -> dict[str, Any]:
        """Run the real agent pipeline (researcher → analyst → strategist).

        The only difference from live execution is that ``vnstock_service``
        functions are monkey-patched to read from the LookbackProvider
        instead of the live API.
        """
        import services.vnstock_service as live_svc
        from agents.nodes import (
            researcher_node, analyst_node, strategist_node,
            _sanitize,
        )
        from models.state import AgentState

        provider = self.p.lookback_provider
        if provider is None:
            return {"signal": SIGNAL_HOLD, "reasoning": "No lookback provider"}

        backtest_svc = VnstockBacktestService(provider)

        # Save original functions
        orig_get_price = live_svc.get_price_history
        orig_get_current = live_svc.get_current_price
        orig_calc_tech = live_svc.calculate_technical_indicators
        orig_get_fin = live_svc.get_financial_ratios

        try:
            # Monkey-patch with backtest service (offline data)
            live_svc.get_price_history = backtest_svc.get_price_history
            live_svc.get_current_price = backtest_svc.get_current_price
            live_svc.calculate_technical_indicators = backtest_svc.calculate_technical_indicators
            live_svc.get_financial_ratios = backtest_svc.get_financial_ratios

            # Build initial state — uses the SAME AgentState as live
            state: AgentState = {
                "ticker": self.p.ticker,
                "mode": self.p.mode,  # ← this controls which LLM nodes use
                "current_price": 0.0,
                "raw_financials": {},
                "raw_news": [],
                "raw_ohlc": {},
                "financial_analysis": None,
                "technical_signals": None,
                "smc_analysis": None,
                "elliott_analysis": None,
                "wyckoff_analysis": None,
                "previous_thesis": None,
                "previous_scenarios": None,
                "current_strategy": None,
                "daily_delta_note": None,
                "final_message": "",
            }

            # Run the SAME nodes as the live pipeline
            state.update(researcher_node(state))
            state.update(analyst_node(state))
            state.update(strategist_node(state))

            # Extract trading signal from the strategy result
            return self._extract_signal(state)

        finally:
            # Restore original functions
            live_svc.get_price_history = orig_get_price
            live_svc.get_current_price = orig_get_current
            live_svc.calculate_technical_indicators = orig_calc_tech
            live_svc.get_financial_ratios = orig_get_fin

    @staticmethod
    def _extract_signal(state: dict) -> dict[str, Any]:
        """Convert pipeline output (InvestmentStrategy) to a trading signal."""
        strategy = state.get("current_strategy")
        if not strategy:
            return {"signal": SIGNAL_HOLD, "reasoning": "No strategy produced", "confidence": 0.3}

        primary = (
            strategy.primary_scenario
            if hasattr(strategy, "primary_scenario")
            else strategy.get("primary_scenario", "BASE") if isinstance(strategy, dict)
            else "BASE"
        )

        if primary == "BULLISH":
            signal = SIGNAL_BUY
        elif primary == "BEARISH":
            signal = SIGNAL_SELL
        else:
            signal = SIGNAL_HOLD

        reasoning = (
            strategy.thesis_summary
            if hasattr(strategy, "thesis_summary")
            else strategy.get("thesis_summary", "Analysis complete") if isinstance(strategy, dict)
            else "Analysis complete"
        )

        return {"signal": signal, "reasoning": reasoning, "confidence": 0.7}

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def _execute_signal(
        self,
        signal: str,
        result: dict,
        current_date: str,
        current_price: float,
    ) -> None:
        """Execute the trading signal."""
        confidence = result.get("confidence", 0.5)

        if signal == SIGNAL_BUY and not self.position:
            cash = self.broker.getcash()
            size = int((cash * self.p.position_size_pct) / current_price)
            if size > 0:
                self.buy(size=size)
                logger.info(
                    "🟢 BUY %d shares @ %.0f on %s (conf=%.0f%%) — %s",
                    size, current_price, current_date,
                    confidence * 100, result.get("reasoning", "")[:60],
                )

        elif signal == SIGNAL_SELL and self.position:
            self.close()
            logger.info(
                "🔴 SELL (close position) @ %.0f on %s (conf=%.0f%%) — %s",
                current_price, current_date,
                confidence * 100, result.get("reasoning", "")[:60],
            )

        else:
            logger.debug(
                "⚪ HOLD @ %.0f on %s — %s",
                current_price, current_date, result.get("reasoning", "")[:60],
            )
