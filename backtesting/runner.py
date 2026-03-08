"""Backtest runner — end-to-end orchestrator.

Downloads historical data from vnstock, sets up Backtrader with the
``AgentStrategy``, runs the simulation, and returns a ``BacktestResult``.

Usage (programmatic)::

    from backtesting.runner import run_backtest
    result = run_backtest("FPT", "2024-01-01", "2024-12-31")
    print(result.summary())
"""

from __future__ import annotations

import logging
from datetime import datetime

import backtrader as bt
import pandas as pd

from backtesting.data_feed import create_data_feed
from backtesting.lookback_provider import LookbackProvider
from backtesting.agent_strategy import AgentStrategy
from backtesting.report import compute_metrics, BacktestResult

logger = logging.getLogger(__name__)


def _download_data(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Download OHLCV data from vnstock for the given date range.

    Parameters
    ----------
    ticker : str
        Stock symbol (e.g. "FPT").
    start_date, end_date : str
        ISO date strings ("YYYY-MM-DD").

    Returns
    -------
    pd.DataFrame
        OHLCV data sorted by time ascending.

    Raises
    ------
    RuntimeError
        If data download fails.
    """
    from vnstock import Vnstock

    logger.info("⬇️  Downloading %s data: %s → %s", ticker, start_date, end_date)

    stock = Vnstock().stock(symbol=ticker, source="VCI")
    df = stock.quote.history(start=start_date, end=end_date)

    if df is None or df.empty:
        raise RuntimeError(f"No data returned for {ticker} ({start_date} → {end_date})")

    # Normalise column names to lowercase
    df.columns = [c.lower() for c in df.columns]

    # Ensure time column exists
    time_col = None
    for candidate in ("time", "date", "datetime"):
        if candidate in df.columns:
            time_col = candidate
            break
    if time_col is None:
        raise RuntimeError(f"No time/date column found. Columns: {list(df.columns)}")

    df[time_col] = pd.to_datetime(df[time_col])
    df = df.sort_values(time_col).reset_index(drop=True)

    logger.info("✅ Downloaded %d bars for %s", len(df), ticker)
    return df


def run_backtest(
    ticker: str,
    start_date: str,
    end_date: str,
    mode: str = "signal_mode",
    initial_cash: float = 100_000_000,
    rebalance_every: int = 2,
    commission: float = 0.0015,
    position_size_pct: float = 0.9,
    max_bars: int = 0,
    plot: bool = False,
) -> BacktestResult:
    """Run a full backtest and return structured results.

    Parameters
    ----------
    ticker : str
        Stock symbol (e.g. "FPT", "VCB").
    start_date, end_date : str
        Date range in "YYYY-MM-DD" format.
    mode : str
        ``"signal_mode"`` (DeepSeek R1) or ``"agent_mode"`` (full Claude).
    initial_cash : float
        Starting capital in VND (default 100M).
    rebalance_every : int
        Re-evaluate strategy every N bars (default 2).
    commission : float
        Commission rate per trade (default 0.15%).
    position_size_pct : float
        Fraction of cash to deploy per trade (default 90%).
    max_bars : int
        Stop after N bars (0 = run all). Useful for testing or limiting cost.
    plot : bool
        Show Backtrader chart after run (default False).

    Returns
    -------
    BacktestResult
        Metrics, trade log, and summary.
    """
    # ── 1. Download data ─────────────────────────────────────────────────
    full_df = _download_data(ticker, start_date, end_date)

    # ── 2. Create anti-look-ahead provider ───────────────────────────────
    lookback_provider = LookbackProvider(full_df)

    # ── 3. Set up Backtrader ─────────────────────────────────────────────
    cerebro = bt.Cerebro()

    # Add data feed
    data_feed = create_data_feed(full_df)
    cerebro.adddata(data_feed)

    # Add strategy
    cerebro.addstrategy(
        AgentStrategy,
        lookback_provider=lookback_provider,
        ticker=ticker.upper(),
        mode=mode,
        rebalance_every=rebalance_every,
        position_size_pct=position_size_pct,
        max_bars=max_bars,
    )

    # Broker settings
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=commission)

    # Add analyzers for metrics
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", riskfreerate=0.03)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")

    # ── 4. Run ───────────────────────────────────────────────────────────
    logger.info(
        "🚀 Starting backtest: %s (%s) | cash=%.0f | mode=%s | rebal=%d | max_bars=%s",
        ticker, f"{start_date}→{end_date}", initial_cash, mode, rebalance_every,
        max_bars or "all",
    )

    interrupted = False
    try:
        results = cerebro.run()
    except KeyboardInterrupt:
        logger.warning("⏹️  Backtest interrupted by user (Ctrl+C) — generating partial report")
        interrupted = True
        # Cerebro still has strategy instances after interrupt
        results = cerebro.runstrats[0] if cerebro.runstrats else []

    # Get strategy instance
    if isinstance(results, list) and results:
        strategy = results[0] if not isinstance(results[0], list) else results[0][0]
    else:
        strategy = results

    early_stopped = interrupted or getattr(strategy, "stopped_early", False)

    # ── 5. Compute metrics ───────────────────────────────────────────────
    close_col = "close" if "close" in full_df.columns else "Close"
    first_close = float(full_df[close_col].iloc[0])

    # For partial runs, use the last bar the strategy actually processed
    if early_stopped and hasattr(strategy, "_bar_count"):
        bars_run = strategy._bar_count
        last_idx = min(bars_run, len(full_df) - 1)
        last_close = float(full_df[close_col].iloc[last_idx])
        actual_end = str(full_df.iloc[last_idx].get("time", end_date))
        logger.info("📊 Partial report: %d / %d bars processed", bars_run, len(full_df))
    else:
        last_close = float(full_df[close_col].iloc[-1])
        actual_end = end_date

    report = compute_metrics(
        cerebro_result=results,
        initial_cash=initial_cash,
        strategy=strategy,
        first_close=first_close,
        last_close=last_close,
        ticker=ticker.upper(),
        start_date=start_date,
        end_date=actual_end,
        mode=mode + (" [PARTIAL]" if early_stopped else ""),
    )

    # ── 6. Output ────────────────────────────────────────────────────────
    print("\n" + report.summary())

    if plot and not interrupted:
        try:
            cerebro.plot(style="candlestick", volume=True)
        except Exception as exc:
            logger.warning("Plot failed (matplotlib issue?): %s", exc)

    return report
