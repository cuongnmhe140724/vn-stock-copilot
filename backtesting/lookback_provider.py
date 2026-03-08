"""Point-in-time data provider — prevents look-ahead bias.

Holds the FULL historical DataFrame but only exposes data up to
the current bar index.  Every time Backtrader advances a bar,
``advance(bar_index)`` is called to update the cutoff.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


class LookbackProvider:
    """Slice a full DataFrame to simulate point-in-time data access.

    This is the **primary defence** against look-ahead bias.  At bar *i*
    the provider only returns rows ``[0 … i]`` — future data is completely
    inaccessible.

    Parameters
    ----------
    full_df : pd.DataFrame
        Complete OHLCV DataFrame (ascending date order).  Must contain at
        least ``time``, ``open``, ``high``, ``low``, ``close``, ``volume``.
    """

    def __init__(self, full_df: pd.DataFrame) -> None:
        if full_df is None or full_df.empty:
            raise ValueError("LookbackProvider requires a non-empty DataFrame")

        # Ensure ascending date order
        time_col = self._find_time_col(full_df)
        self._full_df = full_df.sort_values(time_col).reset_index(drop=True)
        self._time_col = time_col
        self._current_idx: int = 0
        self._total_bars: int = len(self._full_df)

        logger.info(
            "LookbackProvider initialised with %d bars (%s → %s)",
            self._total_bars,
            self._full_df[self._time_col].iloc[0],
            self._full_df[self._time_col].iloc[-1],
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def advance(self, bar_index: int) -> None:
        """Move the cutoff forward — called by ``AgentStrategy.next()``.

        Parameters
        ----------
        bar_index : int
            0-based index of the current Backtrader bar.
        """
        if bar_index < 0 or bar_index >= self._total_bars:
            raise IndexError(
                f"bar_index {bar_index} out of range [0, {self._total_bars})"
            )
        self._current_idx = bar_index

    def get_ohlcv(self, lookback: int = 365) -> pd.DataFrame:
        """Return OHLCV data **up to** (inclusive) the current bar.

        Parameters
        ----------
        lookback : int
            Maximum number of historical bars to return, counting backwards
            from the current bar.

        Returns
        -------
        pd.DataFrame
            Slice of ``[max(0, current-lookback+1) … current]``.
        """
        end = self._current_idx + 1          # exclusive upper bound
        start = max(0, end - lookback)
        return self._full_df.iloc[start:end].copy().reset_index(drop=True)

    def get_current_price(self) -> float:
        """Return the close price at the current bar."""
        close_col = self._find_close_col(self._full_df)
        return float(self._full_df[close_col].iloc[self._current_idx])

    def get_current_bar_date(self) -> str:
        """Return the date string of the current bar."""
        return str(self._full_df[self._time_col].iloc[self._current_idx])

    @property
    def current_index(self) -> int:
        return self._current_idx

    @property
    def total_bars(self) -> int:
        return self._total_bars

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_time_col(df: pd.DataFrame) -> str:
        for candidate in ("time", "date", "datetime", "Date", "Time"):
            if candidate in df.columns:
                return candidate
        raise KeyError(
            f"Cannot find time column in DataFrame. Columns: {list(df.columns)}"
        )

    @staticmethod
    def _find_close_col(df: pd.DataFrame) -> str:
        for candidate in ("close", "Close", "CLOSE"):
            if candidate in df.columns:
                return candidate
        raise KeyError(
            f"Cannot find close column in DataFrame. Columns: {list(df.columns)}"
        )
