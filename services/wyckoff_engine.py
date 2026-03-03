"""Wyckoff analysis engine.

Provides:
  - Volume Profile (volume-at-price histogram)
  - Point of Control (POC)
  - Trading Range detection (Accumulation/Distribution boxes)
  - Phase classification (Accumulation / Distribution / Markup / Markdown)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, List, Literal, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class VolumeLevel:
    price_low: float
    price_high: float
    volume: float


@dataclass
class TradingRange:
    """Wyckoff Trading Range (consolidation box)."""
    upper_bound: float   # AR (Automatic Rally) or high of range
    lower_bound: float   # SC (Selling Climax) or low of range
    start_index: int
    end_index: int
    start_time: Any = None
    end_time: Any = None


class WyckoffEngine:
    """Wyckoff analysis from an OHLCV DataFrame.

    Parameters
    ----------
    df : DataFrame
        OHLCV data sorted ascending by time.
    num_bins : int
        Number of price bins for the volume profile histogram.
    range_lookback : int
        Number of bars to scan for a Trading Range.
    """

    def __init__(
        self,
        df: pd.DataFrame,
        num_bins: int = 50,
        range_lookback: int = 100,
    ) -> None:
        self.df = df.copy().reset_index(drop=True)
        self.num_bins = num_bins
        self.range_lookback = range_lookback

        self._high = self._col("high")
        self._low = self._col("low")
        self._close = self._col("close")
        self._open = self._col("open")
        self._volume = self._col("volume")
        self._time = self._col("time") or self._col("date")

        # Computed data
        self.volume_profile: List[VolumeLevel] = []
        self.poc_level: Optional[VolumeLevel] = None
        self.vah: Optional[float] = None   # Value Area High
        self.val: Optional[float] = None   # Value Area Low
        self.trading_range: Optional[TradingRange] = None
        self.phase: str = "Undetermined"

        self._compute_all()

    def _col(self, keyword: str) -> str | None:
        for c in self.df.columns:
            if keyword.lower() in str(c).lower():
                return c
        return None

    def _compute_all(self) -> None:
        self.compute_volume_profile()
        self.compute_value_area()
        self.detect_trading_range()
        self.detect_phase()

    # ── 1. Volume Profile ────────────────────────────────────────────────

    def compute_volume_profile(self) -> List[VolumeLevel]:
        """Build a volume-at-price histogram.

        Instead of summing volume per time-bar, we distribute each bar's
        volume across the price bins it spans (high ↔ low).
        """
        highs = self.df[self._high].values.astype(float)
        lows = self.df[self._low].values.astype(float)
        volumes = self.df[self._volume].values.astype(float)

        price_min = float(np.nanmin(lows))
        price_max = float(np.nanmax(highs))

        if price_max <= price_min:
            self.volume_profile = []
            return self.volume_profile

        bin_edges = np.linspace(price_min, price_max, self.num_bins + 1)
        bin_volumes = np.zeros(self.num_bins)

        for i in range(len(self.df)):
            bar_low = lows[i]
            bar_high = highs[i]
            bar_vol = volumes[i]

            # Find which bins this bar spans
            first_bin = int(np.searchsorted(bin_edges, bar_low, side="right")) - 1
            last_bin = int(np.searchsorted(bin_edges, bar_high, side="right")) - 1

            first_bin = max(0, min(first_bin, self.num_bins - 1))
            last_bin = max(0, min(last_bin, self.num_bins - 1))

            n_bins_spanned = last_bin - first_bin + 1
            if n_bins_spanned > 0:
                vol_per_bin = bar_vol / n_bins_spanned
                for b in range(first_bin, last_bin + 1):
                    bin_volumes[b] += vol_per_bin

        self.volume_profile = []
        for b in range(self.num_bins):
            self.volume_profile.append(VolumeLevel(
                price_low=round(float(bin_edges[b]), 2),
                price_high=round(float(bin_edges[b + 1]), 2),
                volume=round(float(bin_volumes[b]), 0),
            ))

        # POC = bin with highest volume
        poc_idx = int(np.argmax(bin_volumes))
        self.poc_level = self.volume_profile[poc_idx]

        return self.volume_profile

    # ── 2. Value Area ────────────────────────────────────────────────────

    def compute_value_area(self, pct: float = 0.7) -> None:
        """Compute Value Area containing `pct` (default 70%) of total volume.

        Expand outward from POC bucket until we capture the target percentage.
        """
        if not self.volume_profile or self.poc_level is None:
            return

        volumes = [vl.volume for vl in self.volume_profile]
        total_vol = sum(volumes)
        if total_vol == 0:
            return

        target = total_vol * pct
        poc_idx = volumes.index(self.poc_level.volume)

        accumulated = volumes[poc_idx]
        lo, hi = poc_idx, poc_idx

        while accumulated < target and (lo > 0 or hi < len(volumes) - 1):
            # Expand toward the side with more volume
            expand_lo = volumes[lo - 1] if lo > 0 else 0
            expand_hi = volumes[hi + 1] if hi < len(volumes) - 1 else 0

            if expand_lo >= expand_hi and lo > 0:
                lo -= 1
                accumulated += volumes[lo]
            elif hi < len(volumes) - 1:
                hi += 1
                accumulated += volumes[hi]
            else:
                lo -= 1
                accumulated += volumes[lo]

        self.val = self.volume_profile[lo].price_low
        self.vah = self.volume_profile[hi].price_high

    # ── 3. Trading Range detection ───────────────────────────────────────

    def detect_trading_range(self) -> Optional[TradingRange]:
        """Detect the most recent consolidation (Trading Range).

        Heuristic: Find the longest recent period where price stays within
        a defined percentage of the range (ATR-based or % of price).
        The upper/lower bounds correspond to AR (Automatic Rally) and
        SC (Selling Climax) in Wyckoff terminology.
        """
        n = len(self.df)
        lookback = min(self.range_lookback, n)
        subset = self.df.tail(lookback).copy().reset_index(drop=True)

        highs = subset[self._high].values.astype(float)
        lows = subset[self._low].values.astype(float)
        closes = subset[self._close].values.astype(float)

        # Use the median range as a reference
        overall_high = float(np.max(highs))
        overall_low = float(np.min(lows))
        overall_range = overall_high - overall_low

        if overall_range == 0:
            self.trading_range = None
            return None

        # Find the tightest sub-range that contains at least 70% of bars
        best_range = None
        best_score = float("inf")  # lower = tighter

        # Sliding window approach: try different range sizes
        for start_i in range(0, lookback - 20):
            for end_i in range(start_i + 20, lookback):
                window_highs = highs[start_i:end_i + 1]
                window_lows = lows[start_i:end_i + 1]
                w_high = float(np.max(window_highs))
                w_low = float(np.min(window_lows))
                w_range = w_high - w_low

                # A "range" should be relatively tight compared to overall
                range_ratio = w_range / overall_range if overall_range > 0 else 1
                length = end_i - start_i + 1

                # Score: prefer longer, tighter ranges
                if range_ratio < 0.6 and length >= 20:
                    score = range_ratio / (length / lookback)
                    if score < best_score:
                        best_score = score
                        actual_start = n - lookback + start_i
                        actual_end = n - lookback + end_i
                        t_start = (
                            self.df[self._time].iloc[actual_start]
                            if self._time else None
                        )
                        t_end = (
                            self.df[self._time].iloc[actual_end]
                            if self._time else None
                        )
                        best_range = TradingRange(
                            upper_bound=round(w_high, 2),
                            lower_bound=round(w_low, 2),
                            start_index=actual_start,
                            end_index=actual_end,
                            start_time=t_start,
                            end_time=t_end,
                        )

        self.trading_range = best_range
        return self.trading_range

    # ── 4. Phase detection ───────────────────────────────────────────────

    def detect_phase(self) -> str:
        """Classify into Wyckoff phases based on price action + volume.

        Phases:
          - Accumulation: price at bottom of range, volume rising on up-moves
          - Distribution: price at top of range, volume rising on down-moves
          - Markup: price breaking above range
          - Markdown: price breaking below range
        """
        closes = self.df[self._close].values.astype(float)
        volumes = self.df[self._volume].values.astype(float)
        latest_close = closes[-1]

        if self.trading_range is None:
            # No range found — check trend direction
            if len(closes) > 20:
                ma20 = np.mean(closes[-20:])
                if latest_close > ma20 * 1.02:
                    self.phase = "Markup"
                elif latest_close < ma20 * 0.98:
                    self.phase = "Markdown"
                else:
                    self.phase = "Undetermined"
            else:
                self.phase = "Undetermined"
            return self.phase

        tr = self.trading_range
        mid = (tr.upper_bound + tr.lower_bound) / 2

        # Is price still inside the range?
        if latest_close > tr.upper_bound * 1.02:
            self.phase = "Markup"
        elif latest_close < tr.lower_bound * 0.98:
            self.phase = "Markdown"
        else:
            # Inside range — check volume patterns
            range_data = self.df.iloc[tr.start_index:tr.end_index + 1]
            opens = range_data[self._open].values.astype(float)
            range_closes = range_data[self._close].values.astype(float)
            range_volumes = range_data[self._volume].values.astype(float)

            up_volume = 0.0
            down_volume = 0.0
            for i in range(len(range_data)):
                if range_closes[i] >= opens[i]:
                    up_volume += range_volumes[i]
                else:
                    down_volume += range_volumes[i]

            if latest_close <= mid:
                # Price in lower half
                if up_volume > down_volume:
                    self.phase = "Accumulation"
                else:
                    self.phase = "Markdown (potential)"
            else:
                # Price in upper half
                if down_volume > up_volume:
                    self.phase = "Distribution"
                else:
                    self.phase = "Markup (potential)"

        return self.phase

    # ── Public API ───────────────────────────────────────────────────────

    def get_poc(self) -> dict | None:
        """Return the Point of Control (price level with highest volume)."""
        if self.poc_level is None:
            return None
        return {
            "price_low": self.poc_level.price_low,
            "price_high": self.poc_level.price_high,
            "volume": self.poc_level.volume,
        }

    def get_value_area(self) -> dict | None:
        """Return Value Area High/Low."""
        if self.vah is None or self.val is None:
            return None
        return {"value_area_high": self.vah, "value_area_low": self.val}

    def get_trading_range(self) -> dict | None:
        """Return the detected Trading Range box."""
        if self.trading_range is None:
            return None
        tr = self.trading_range
        return {
            "upper_bound_AR": tr.upper_bound,
            "lower_bound_SC": tr.lower_bound,
            "start_time": str(tr.start_time) if tr.start_time else None,
            "end_time": str(tr.end_time) if tr.end_time else None,
        }

    def get_phase(self) -> str:
        """Return the current Wyckoff phase."""
        return self.phase

    def summary(self) -> dict:
        """Return a full Wyckoff summary dict for LLM consumption."""
        return {
            "phase": self.get_phase(),
            "point_of_control": self.get_poc(),
            "value_area": self.get_value_area(),
            "trading_range": self.get_trading_range(),
            "volume_profile_bins": len(self.volume_profile),
        }
