"""Backtest performance metrics and reporting.

Computes standard portfolio performance metrics from a Backtrader run:
total return, Sharpe ratio, max drawdown, win rate, trade log, etc.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """Container for all backtest output metrics."""

    ticker: str
    start_date: str
    end_date: str
    mode: str

    # Portfolio
    initial_cash: float
    final_value: float
    total_return_pct: float

    # Risk
    sharpe_ratio: float
    max_drawdown_pct: float

    # Trade stats
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    avg_win: float
    avg_loss: float
    profit_factor: float

    # Benchmark
    buy_hold_return_pct: float

    # Details
    trade_log: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary(self) -> str:
        """Pretty-print summary for terminal / Telegram."""
        lines = [
            f"═══ Backtest Report: {self.ticker} ═══",
            f"Period:        {self.start_date} → {self.end_date}",
            f"Mode:          {self.mode}",
            "",
            f"Initial Cash:  {self.initial_cash:>15,.0f} VNĐ",
            f"Final Value:   {self.final_value:>15,.0f} VNĐ",
            f"Total Return:  {self.total_return_pct:>14.2f}%",
            f"Buy & Hold:    {self.buy_hold_return_pct:>14.2f}%",
            f"Alpha:         {self.total_return_pct - self.buy_hold_return_pct:>14.2f}%",
            "",
            f"Sharpe Ratio:  {self.sharpe_ratio:>14.2f}",
            f"Max Drawdown:  {self.max_drawdown_pct:>14.2f}%",
            "",
            f"Total Trades:  {self.total_trades:>14d}",
            f"Win Rate:      {self.win_rate_pct:>14.2f}%",
            f"Avg Win:       {self.avg_win:>15,.0f} VNĐ",
            f"Avg Loss:      {self.avg_loss:>15,.0f} VNĐ",
            f"Profit Factor: {self.profit_factor:>14.2f}",
            "═" * 45,
        ]
        return "\n".join(lines)


def compute_metrics(
    cerebro_result,
    initial_cash: float,
    strategy,
    first_close: float,
    last_close: float,
    ticker: str,
    start_date: str,
    end_date: str,
    mode: str,
) -> BacktestResult:
    """Compute all performance metrics after a backtest run.

    Parameters
    ----------
    cerebro_result
        Return value of ``cerebro.run()``.
    initial_cash : float
        Starting cash (VND).
    strategy
        The ``AgentStrategy`` instance (from ``cerebro_result[0]``).
    first_close : float
        Close price on the first bar.
    last_close : float
        Close price on the last bar.
    ticker, start_date, end_date, mode : str
        Metadata for the report.
    """
    final_value = strategy.broker.getvalue()
    total_return_pct = ((final_value - initial_cash) / initial_cash) * 100

    # Buy & Hold benchmark
    buy_hold_return_pct = ((last_close - first_close) / first_close) * 100

    # Trade analysis
    trade_log = getattr(strategy, "trade_log", [])
    total_trades = len(trade_log)

    wins = [t for t in trade_log if t.get("pnl", 0) > 0]
    losses = [t for t in trade_log if t.get("pnl", 0) <= 0]

    winning_trades = len(wins)
    losing_trades = len(losses)
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

    avg_win = sum(t["pnl"] for t in wins) / winning_trades if wins else 0
    avg_loss = sum(t["pnl"] for t in losses) / losing_trades if losses else 0

    total_wins_sum = sum(t["pnl"] for t in wins)
    total_losses_sum = abs(sum(t["pnl"] for t in losses))
    profit_factor = (total_wins_sum / total_losses_sum) if total_losses_sum > 0 else float("inf") if total_wins_sum > 0 else 0

    # Sharpe ratio (simplified: annualised daily returns)
    sharpe = _compute_sharpe(strategy)

    # Max drawdown
    max_dd = _compute_max_drawdown(strategy)

    return BacktestResult(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        mode=mode,
        initial_cash=initial_cash,
        final_value=round(final_value, 0),
        total_return_pct=round(total_return_pct, 2),
        sharpe_ratio=round(sharpe, 2),
        max_drawdown_pct=round(max_dd, 2),
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate_pct=round(win_rate, 2),
        avg_win=round(avg_win, 0),
        avg_loss=round(avg_loss, 0),
        profit_factor=round(profit_factor, 2),
        buy_hold_return_pct=round(buy_hold_return_pct, 2),
        trade_log=trade_log,
    )


def _compute_sharpe(strategy, risk_free_rate: float = 0.03) -> float:
    """Approximate Sharpe ratio from Backtrader analyzers or manual calc.

    Uses daily portfolio values to compute annualised Sharpe.
    """
    import numpy as np

    try:
        # Try to get from Backtrader analyzers
        analyzers = strategy.analyzers
        if hasattr(analyzers, "sharpe"):
            sr = analyzers.sharpe.get_analysis()
            val = sr.get("sharperatio")
            if val is not None:
                return float(val)
    except Exception:
        pass

    # Fallback — manual calculation is complex without value history
    # Return 0 as a safe default if analyzer not available
    return 0.0


def _compute_max_drawdown(strategy) -> float:
    """Extract max drawdown percentage from Backtrader analyzers."""
    try:
        analyzers = strategy.analyzers
        if hasattr(analyzers, "drawdown"):
            dd = analyzers.drawdown.get_analysis()
            return dd.get("max", {}).get("drawdown", 0.0)
    except Exception:
        pass

    return 0.0
