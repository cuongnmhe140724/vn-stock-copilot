"""Offline data service for backtesting — drop-in replacement for vnstock_service.

All methods mirror the real ``vnstock_service`` interface but read from a
``LookbackProvider`` instead of calling the live API.  This ensures the agent
only ever sees point-in-time data during a backtest.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from backtesting.lookback_provider import LookbackProvider
# Import the REAL function at module-load time — before any monkey-patching.
# This reference survives monkey-patching of vnstock_service module attributes.
from services.vnstock_service import calculate_technical_indicators as _real_calc_tech

logger = logging.getLogger(__name__)


class VnstockBacktestService:
    """Point-in-time vnstock_service replacement.

    Parameters
    ----------
    lookback_provider : LookbackProvider
        Shared provider with a bar-cutoff managed by the strategy.
    financial_data : dict | None
        Optional pre-loaded financial ratios (quarterly data is not
        time-varying bar-by-bar, so we use a fixed snapshot).
    """

    def __init__(
        self,
        lookback_provider: LookbackProvider,
        financial_data: dict | None = None,
    ) -> None:
        self._provider = lookback_provider
        self._financial_data = financial_data or self._default_financials()

    # ------------------------------------------------------------------
    # Mirror interfaces from vnstock_service
    # ------------------------------------------------------------------

    def get_price_history(self, ticker: str, days: int = 365) -> pd.DataFrame:
        """Return OHLCV data up to the current bar."""
        return self._provider.get_ohlcv(lookback=days)

    def get_current_price(self, ticker: str) -> dict[str, Any]:
        """Return latest close price at the current bar."""
        price = self._provider.get_current_price()
        return {
            "ticker": ticker,
            "latest_close": price,
            "date": self._provider.get_current_bar_date(),
        }

    def get_financial_ratios(self, ticker: str, periods: int = 8) -> dict[str, Any]:
        """Return fixed financial data (not time-varying in backtest)."""
        return self._financial_data

    def calculate_technical_indicators(self, df: pd.DataFrame) -> dict[str, Any]:
        """Compute indicators on the given (already-sliced) DataFrame.

        Uses the real ``vnstock_service`` logic (imported at module load
        time, so it survives monkey-patching).
        """
        return _real_calc_tech(df)

    # ------------------------------------------------------------------
    # Default / mock financials
    # ------------------------------------------------------------------

    @staticmethod
    def _default_financials() -> dict[str, Any]:
        """Neutral financial data used when no real data is provided."""
        return {
            "revenue_growth": 0.0,
            "profit_growth": 0.0,
            "roe": 0.0,
            "pe_ratio": 0.0,
            "debt_to_equity": 0.0,
            "raw_ratios": {},
            "note": "Backtest mode — financial data not available bar-by-bar",
        }
