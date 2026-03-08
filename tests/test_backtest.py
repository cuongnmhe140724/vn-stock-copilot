"""Unit and integration tests for the backtesting system.

Tests cover:
  1. LookbackProvider — anti-look-ahead bias verification
  2. VnstockBacktestService — mirrors vnstock_service interface
  3. VnstockDataFeed — column normalisation
  4. BacktestResult — metrics computation
  5. Look-ahead bias detection — future data must be inaccessible

Run:
    python -m pytest tests/test_backtest.py -v
"""

from __future__ import annotations

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


# ── Test helpers ─────────────────────────────────────────────────────────────

def _make_ohlcv(n: int = 100, start_price: float = 50000) -> pd.DataFrame:
    """Generate a synthetic OHLCV DataFrame mimicking vnstock output."""
    dates = pd.date_range(start="2024-01-01", periods=n, freq="B")  # business days
    np.random.seed(42)
    closes = start_price + np.cumsum(np.random.randn(n) * 500)
    closes = np.maximum(closes, 1000)  # prevent negative prices

    df = pd.DataFrame({
        "time": dates,
        "open": closes * (1 + np.random.uniform(-0.01, 0.01, n)),
        "high": closes * (1 + np.random.uniform(0, 0.03, n)),
        "low": closes * (1 + np.random.uniform(-0.03, 0, n)),
        "close": closes,
        "volume": np.random.randint(100_000, 5_000_000, n),
    })
    return df


# ═════════════════════════════════════════════════════════════════════════════
# 1. LookbackProvider Tests
# ═════════════════════════════════════════════════════════════════════════════

class TestLookbackProvider:
    """Test that LookbackProvider never leaks future data."""

    def test_initial_state_returns_one_row(self):
        from backtesting.lookback_provider import LookbackProvider

        df = _make_ohlcv(50)
        lp = LookbackProvider(df)
        # At bar 0, should return at most 1 row
        result = lp.get_ohlcv(lookback=365)
        assert len(result) == 1, f"Expected 1 row at bar 0, got {len(result)}"

    def test_advance_returns_correct_slice(self):
        from backtesting.lookback_provider import LookbackProvider

        df = _make_ohlcv(100)
        lp = LookbackProvider(df)

        # Advance to bar 49
        lp.advance(49)
        result = lp.get_ohlcv(lookback=365)
        assert len(result) == 50, f"Expected 50 rows at bar 49, got {len(result)}"

    def test_lookback_limits_result(self):
        from backtesting.lookback_provider import LookbackProvider

        df = _make_ohlcv(100)
        lp = LookbackProvider(df)

        lp.advance(99)  # last bar
        result = lp.get_ohlcv(lookback=20)
        assert len(result) == 20, f"Expected 20 rows with lookback=20, got {len(result)}"

    def test_no_future_data_leak(self):
        """CRITICAL: Verify that data after current bar is NEVER returned."""
        from backtesting.lookback_provider import LookbackProvider

        df = _make_ohlcv(100)
        lp = LookbackProvider(df)

        for bar_idx in range(0, 100, 10):
            lp.advance(bar_idx)
            result = lp.get_ohlcv(lookback=365)
            max_rows = bar_idx + 1
            assert len(result) <= max_rows, (
                f"LOOK-AHEAD BIAS at bar {bar_idx}: "
                f"got {len(result)} rows, max allowed {max_rows}"
            )

    def test_current_price_matches_bar(self):
        from backtesting.lookback_provider import LookbackProvider

        df = _make_ohlcv(100)
        lp = LookbackProvider(df)

        for bar_idx in [0, 25, 50, 99]:
            lp.advance(bar_idx)
            price = lp.get_current_price()
            expected = float(df["close"].iloc[bar_idx])
            assert abs(price - expected) < 0.01, (
                f"Price mismatch at bar {bar_idx}: {price} != {expected}"
            )

    def test_out_of_range_raises(self):
        from backtesting.lookback_provider import LookbackProvider

        df = _make_ohlcv(50)
        lp = LookbackProvider(df)

        with pytest.raises(IndexError):
            lp.advance(50)  # only 0-49 valid

        with pytest.raises(IndexError):
            lp.advance(-1)

    def test_empty_df_raises(self):
        from backtesting.lookback_provider import LookbackProvider

        with pytest.raises(ValueError):
            LookbackProvider(pd.DataFrame())


# ═════════════════════════════════════════════════════════════════════════════
# 2. VnstockBacktestService Tests
# ═════════════════════════════════════════════════════════════════════════════

class TestVnstockBacktestService:
    """Test the offline data service."""

    def test_get_price_history_uses_provider(self):
        from backtesting.lookback_provider import LookbackProvider
        from services.vnstock_backtest_service import VnstockBacktestService

        df = _make_ohlcv(100)
        lp = LookbackProvider(df)
        svc = VnstockBacktestService(lp)

        lp.advance(30)
        result = svc.get_price_history("FPT", days=365)
        assert len(result) == 31  # bars 0-30

    def test_get_current_price(self):
        from backtesting.lookback_provider import LookbackProvider
        from services.vnstock_backtest_service import VnstockBacktestService

        df = _make_ohlcv(50)
        lp = LookbackProvider(df)
        svc = VnstockBacktestService(lp)

        lp.advance(10)
        info = svc.get_current_price("FPT")
        assert info["ticker"] == "FPT"
        expected_price = float(df["close"].iloc[10])
        assert abs(info["latest_close"] - expected_price) < 0.01

    def test_financial_ratios_returns_default(self):
        from backtesting.lookback_provider import LookbackProvider
        from services.vnstock_backtest_service import VnstockBacktestService

        df = _make_ohlcv(50)
        lp = LookbackProvider(df)
        svc = VnstockBacktestService(lp)

        ratios = svc.get_financial_ratios("FPT")
        assert "note" in ratios  # default mock data


# ═════════════════════════════════════════════════════════════════════════════
# 3. DataFeed Tests
# ═════════════════════════════════════════════════════════════════════════════

class TestVnstockDataFeed:
    """Test column normalisation for Backtrader."""

    def test_normalise_columns(self):
        from backtesting.data_feed import _normalise_columns

        df = _make_ohlcv(10)
        result = _normalise_columns(df)
        assert "datetime" in result.columns
        assert "open" in result.columns
        assert "close" in result.columns
        assert "time" not in result.columns  # renamed to datetime


# ═════════════════════════════════════════════════════════════════════════════
# 4. Report Tests
# ═════════════════════════════════════════════════════════════════════════════

class TestBacktestResult:
    """Test the result container."""

    def test_summary_output(self):
        from backtesting.report import BacktestResult

        result = BacktestResult(
            ticker="FPT",
            start_date="2024-01-01",
            end_date="2024-12-31",
            mode="signal_mode",
            initial_cash=100_000_000,
            final_value=115_000_000,
            total_return_pct=15.0,
            sharpe_ratio=1.2,
            max_drawdown_pct=-8.5,
            total_trades=10,
            winning_trades=6,
            losing_trades=4,
            win_rate_pct=60.0,
            avg_win=3_000_000,
            avg_loss=-1_500_000,
            profit_factor=2.0,
            buy_hold_return_pct=10.0,
            trade_log=[],
        )
        summary = result.summary()
        assert "FPT" in summary
        assert "15.00%" in summary
        assert "Alpha" in summary

    def test_to_dict(self):
        from backtesting.report import BacktestResult

        result = BacktestResult(
            ticker="VCB", start_date="2024-01-01", end_date="2024-06-30",
            mode="signal_mode", initial_cash=100_000_000, final_value=105_000_000,
            total_return_pct=5.0, sharpe_ratio=0.8, max_drawdown_pct=-3.0,
            total_trades=5, winning_trades=3, losing_trades=2,
            win_rate_pct=60.0, avg_win=2_000_000, avg_loss=-1_000_000,
            profit_factor=1.5, buy_hold_return_pct=4.0,
        )
        d = result.to_dict()
        assert d["ticker"] == "VCB"
        assert isinstance(d["trade_log"], list)


# ═════════════════════════════════════════════════════════════════════════════
# 5. Look-ahead Bias Detection Test
# ═════════════════════════════════════════════════════════════════════════════

class TestLookAheadBiasDetection:
    """Verify that injecting a future signal does NOT affect current decisions."""

    def test_future_spike_invisible(self):
        """Create a huge price spike at bar N+10, verify LookbackProvider
        at bar N does not contain it."""
        from backtesting.lookback_provider import LookbackProvider

        df = _make_ohlcv(100)

        # Inject a massive spike at bar 60
        df.at[60, "close"] = 999_999
        df.at[60, "high"] = 999_999

        lp = LookbackProvider(df)

        # At bar 50, the spike at 60 must be invisible
        lp.advance(50)
        visible_data = lp.get_ohlcv(lookback=365)

        assert len(visible_data) == 51  # bars 0-50
        assert 999_999 not in visible_data["close"].values, (
            "LOOK-AHEAD BIAS: Future spike at bar 60 is visible at bar 50!"
        )
        assert 999_999 not in visible_data["high"].values, (
            "LOOK-AHEAD BIAS: Future spike high at bar 60 is visible at bar 50!"
        )

        # But at bar 60, it should be visible
        lp.advance(60)
        visible_data = lp.get_ohlcv(lookback=365)
        assert 999_999 in visible_data["close"].values, (
            "Spike should be visible at bar 60"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
