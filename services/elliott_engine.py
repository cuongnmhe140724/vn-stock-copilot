"""Elliott Wave analysis engine.

Uses a ZigZag filter to reduce noise and a rules engine to label impulse
(waves 1-5) and corrective (A-B-C) structures per Elliott Wave Theory.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, List, Literal, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class ZigZagPivot:
    index: int
    price: float
    type: Literal["high", "low"]
    time: Any = None


@dataclass
class WaveLabel:
    pivot_index: int
    price: float
    label: str  # "0", "1", "2", "3", "4", "5", "A", "B", "C"
    time: Any = None


@dataclass
class WaveStatus:
    phase: str          # "Impulse (1-5)" or "Correction (A-B-C)" or "Undetermined"
    label: str          # e.g. "Wave 3", "Wave C"
    sub_wave: str       # e.g. "Sub-wave 3 of 3"
    confidence: str     # "High", "Medium", "Low"


# ── Main engine ──────────────────────────────────────────────────────────────

class ElliottWaveEngine:
    """Identify Elliott Wave structures from OHLCV data.

    Parameters
    ----------
    df : DataFrame
        OHLCV data sorted ascending by time.
    zigzag_threshold : float
        Minimum percentage move to qualify as a ZigZag leg (default 5%).
    """

    def __init__(self, df: pd.DataFrame, zigzag_threshold: float = 0.05) -> None:
        self.df = df.copy().reset_index(drop=True)
        self.zigzag_threshold = zigzag_threshold

        self._high = self._col("high")
        self._low = self._col("low")
        self._close = self._col("close")
        self._time = self._col("time") or self._col("date")

        self.pivots: List[ZigZagPivot] = []
        self.wave_labels: List[WaveLabel] = []
        self._current_status: Optional[WaveStatus] = None
        self._targets: List[dict] = []
        self._invalidation: Optional[float] = None

        self._compute_all()

    def _col(self, keyword: str) -> str | None:
        for c in self.df.columns:
            if keyword.lower() in str(c).lower():
                return c
        return None

    def _compute_all(self) -> None:
        self.compute_zigzag()
        if len(self.pivots) >= 6:
            self._label_waves()
        else:
            self._current_status = WaveStatus(
                phase="Undetermined",
                label="Insufficient pivots",
                sub_wave="N/A",
                confidence="Low",
            )

    # ── ZigZag filter ────────────────────────────────────────────────────

    def compute_zigzag(self) -> List[ZigZagPivot]:
        """Build ZigZag pivot list filtering moves < threshold %."""
        highs = self.df[self._high].values.astype(float)
        lows = self.df[self._low].values.astype(float)
        n = len(self.df)

        if n < 3:
            self.pivots = []
            return self.pivots

        # Find initial direction
        self.pivots = []
        threshold = self.zigzag_threshold

        # State machine: track current potential high/low
        last_high_idx = 0
        last_high_val = highs[0]
        last_low_idx = 0
        last_low_val = lows[0]
        direction = 0  # 1 = looking for high, -1 = looking for low

        # Initialize: find first significant move
        for i in range(1, n):
            if highs[i] > last_high_val:
                last_high_idx = i
                last_high_val = highs[i]
            if lows[i] < last_low_val:
                last_low_idx = i
                last_low_val = lows[i]

            up_move = (last_high_val - lows[0]) / lows[0] if lows[0] > 0 else 0
            down_move = (highs[0] - last_low_val) / highs[0] if highs[0] > 0 else 0

            if up_move >= threshold and direction == 0:
                # First move is up: first pivot is a low
                t = self.df[self._time].iloc[0] if self._time else None
                self.pivots.append(ZigZagPivot(0, lows[0], "low", t))
                direction = 1  # now looking for the high
                break
            elif down_move >= threshold and direction == 0:
                t = self.df[self._time].iloc[0] if self._time else None
                self.pivots.append(ZigZagPivot(0, highs[0], "high", t))
                direction = -1  # now looking for the low
                break

        if direction == 0:
            self.pivots = []
            return self.pivots

        # Main ZigZag loop
        curr_high_idx, curr_high = last_high_idx, last_high_val
        curr_low_idx, curr_low = last_low_idx, last_low_val

        for i in range(1, n):
            if direction == 1:  # Looking for a high
                if highs[i] > curr_high:
                    curr_high = highs[i]
                    curr_high_idx = i
                # Check reversal: price dropped enough from current peak
                drop = (curr_high - lows[i]) / curr_high if curr_high > 0 else 0
                if drop >= threshold and i > curr_high_idx:
                    t = self.df[self._time].iloc[curr_high_idx] if self._time else None
                    self.pivots.append(
                        ZigZagPivot(curr_high_idx, curr_high, "high", t)
                    )
                    direction = -1
                    curr_low = lows[i]
                    curr_low_idx = i

            else:  # direction == -1, looking for a low
                if lows[i] < curr_low:
                    curr_low = lows[i]
                    curr_low_idx = i
                # Check reversal: price rose enough from current trough
                rise = (highs[i] - curr_low) / curr_low if curr_low > 0 else 0
                if rise >= threshold and i > curr_low_idx:
                    t = self.df[self._time].iloc[curr_low_idx] if self._time else None
                    self.pivots.append(
                        ZigZagPivot(curr_low_idx, curr_low, "low", t)
                    )
                    direction = 1
                    curr_high = highs[i]
                    curr_high_idx = i

        # Append the last pending pivot
        if direction == 1:
            t = self.df[self._time].iloc[curr_high_idx] if self._time else None
            self.pivots.append(ZigZagPivot(curr_high_idx, curr_high, "high", t))
        else:
            t = self.df[self._time].iloc[curr_low_idx] if self._time else None
            self.pivots.append(ZigZagPivot(curr_low_idx, curr_low, "low", t))

        return self.pivots

    # ── Wave labelling (rules engine) ────────────────────────────────────

    def _label_waves(self) -> None:
        """Try to fit the last pivots into an impulse (1-5) or corrective (A-B-C) pattern.

        Cardinal Elliott rules (violations invalidate the count):
          Rule 1: Wave 2 NEVER retraces more than 100% of Wave 1.
          Rule 2: Wave 3 is NEVER the shortest of waves 1, 3, 5.
          Rule 3: Wave 4 bottom does NOT overlap Wave 1 top (in non-diagonal).
        """
        pivots = self.pivots

        # Try impulse pattern on the last 6 pivots (points 0-5 = waves 1-5)
        if len(pivots) >= 6:
            impulse = self._try_impulse(pivots[-6:])
            if impulse:
                self._current_status = impulse
                self._compute_impulse_targets(pivots[-6:])
                return

        # Try corrective A-B-C on the last 4 pivots
        if len(pivots) >= 4:
            correction = self._try_correction(pivots[-4:])
            if correction:
                self._current_status = correction
                self._compute_correction_targets(pivots[-4:])
                return

        # Fallback
        self._current_status = WaveStatus(
            phase="Undetermined",
            label="No clear pattern",
            sub_wave="N/A",
            confidence="Low",
        )

    def _try_impulse(self, pts: List[ZigZagPivot]) -> Optional[WaveStatus]:
        """Attempt to label 6 pivots as an impulse wave 0-1-2-3-4-5.

        For a bullish impulse: 0=low, 1=high, 2=low, 3=high, 4=low, 5=high
        For a bearish impulse: 0=high, 1=low, 2=high, 3=low, 4=high, 5=low
        """
        p = [pt.price for pt in pts]

        # Detect direction
        if pts[0].type == "low" and pts[1].type == "high":
            # Bullish impulse
            w1 = p[1] - p[0]
            w2_retrace = p[1] - p[2]
            w3 = p[3] - p[2]
            w4_retrace = p[3] - p[4]
            w5 = p[5] - p[4]

            # Rule 1: Wave 2 cannot retrace > 100% of Wave 1
            if w1 <= 0 or w2_retrace / w1 > 1.0:
                return None

            # Rule 2: Wave 3 cannot be shortest
            if w3 <= 0:
                return None
            if w3 < w1 and w3 < w5:
                return None

            # Rule 3: Wave 4 low cannot overlap Wave 1 high
            if p[4] < p[1]:
                return None

            direction = "bullish"

        elif pts[0].type == "high" and pts[1].type == "low":
            # Bearish impulse
            w1 = p[0] - p[1]
            w2_retrace = p[2] - p[1]
            w3 = p[2] - p[3]
            w4_retrace = p[4] - p[3]
            w5 = p[4] - p[5]

            # Rule 1
            if w1 <= 0 or w2_retrace / w1 > 1.0:
                return None

            # Rule 2
            if w3 <= 0:
                return None
            if w3 < w1 and w3 < w5:
                return None

            # Rule 3
            if p[4] > p[1]:
                return None

            direction = "bearish"
        else:
            return None

        # Label all pivots
        labels = ["0", "1", "2", "3", "4", "5"]
        self.wave_labels = []
        for i, pt in enumerate(pts):
            self.wave_labels.append(WaveLabel(
                pivot_index=pt.index, price=pt.price,
                label=labels[i],
                time=str(pt.time) if pt.time else None,
            ))

        # Determine where we are now (latest price relative to last pivot)
        latest_close = float(self.df[self._close].iloc[-1])
        last_pivot = pts[-1]

        # If the latest close is beyond Wave 5, the impulse is complete
        if direction == "bullish" and latest_close >= last_pivot.price:
            current_label = "Post Wave 5 (Impulse complete)"
        elif direction == "bearish" and latest_close <= last_pivot.price:
            current_label = "Post Wave 5 (Impulse complete)"
        else:
            current_label = "Wave 5"

        # Invalidation
        if direction == "bullish":
            self._invalidation = p[0]  # below wave 0 invalidates
        else:
            self._invalidation = p[0]  # above wave 0 invalidates

        return WaveStatus(
            phase=f"Impulse (1-5) {direction.title()}",
            label=current_label,
            sub_wave="Primary degree",
            confidence="Medium",
        )

    def _try_correction(self, pts: List[ZigZagPivot]) -> Optional[WaveStatus]:
        """Try to label 4 pivots as a corrective A-B-C pattern."""
        p = [pt.price for pt in pts]

        if pts[0].type == "high" and pts[1].type == "low":
            # Bearish correction: A down, B up, C down
            wave_a = p[0] - p[1]
            wave_b = p[2] - p[1]
            wave_c = p[2] - p[3]

            if wave_a <= 0 or wave_b <= 0 or wave_c <= 0:
                return None

            # B should not exceed start of A
            if p[2] > p[0]:
                return None

            direction = "bearish"

        elif pts[0].type == "low" and pts[1].type == "high":
            # Bullish correction: A up, B down, C up
            wave_a = p[1] - p[0]
            wave_b = p[1] - p[2]
            wave_c = p[3] - p[2]

            if wave_a <= 0 or wave_b <= 0 or wave_c <= 0:
                return None

            if p[2] < p[0]:
                return None

            direction = "bullish"
        else:
            return None

        labels = ["Pre-A", "A", "B", "C"]
        self.wave_labels = []
        for i, pt in enumerate(pts):
            self.wave_labels.append(WaveLabel(
                pivot_index=pt.index, price=pt.price,
                label=labels[i],
                time=str(pt.time) if pt.time else None,
            ))

        if direction == "bearish":
            self._invalidation = p[0]
        else:
            self._invalidation = p[0]

        return WaveStatus(
            phase=f"Correction (A-B-C) {direction.title()}",
            label="Wave C",
            sub_wave="Primary degree",
            confidence="Medium",
        )

    # ── Fibonacci targets ────────────────────────────────────────────────

    def _compute_impulse_targets(self, pts: List[ZigZagPivot]) -> None:
        """Compute Fibonacci extension targets based on impulse waves."""
        p = [pt.price for pt in pts]
        w1 = abs(p[1] - p[0])

        is_bullish = pts[0].type == "low"

        if is_bullish:
            base = p[4]  # Wave 4 end
            self._targets = [
                {"level": "100%", "price": round(base + w1, 2)},
                {"level": "161.8%", "price": round(base + w1 * 1.618, 2)},
                {"level": "261.8%", "price": round(base + w1 * 2.618, 2)},
            ]
        else:
            base = p[4]
            self._targets = [
                {"level": "100%", "price": round(base - w1, 2)},
                {"level": "161.8%", "price": round(base - w1 * 1.618, 2)},
                {"level": "261.8%", "price": round(base - w1 * 2.618, 2)},
            ]

    def _compute_correction_targets(self, pts: List[ZigZagPivot]) -> None:
        """Compute Fibonacci retracement targets for correction."""
        p = [pt.price for pt in pts]
        wave_a_len = abs(p[1] - p[0])

        is_bearish_correction = pts[0].type == "high"

        if is_bearish_correction:
            base = p[2]  # end of wave B
            self._targets = [
                {"level": "100% of A", "price": round(base - wave_a_len, 2)},
                {"level": "161.8% of A", "price": round(base - wave_a_len * 1.618, 2)},
            ]
        else:
            base = p[2]
            self._targets = [
                {"level": "100% of A", "price": round(base + wave_a_len, 2)},
                {"level": "161.8% of A", "price": round(base + wave_a_len * 1.618, 2)},
            ]

    # ── Public API ───────────────────────────────────────────────────────

    def identify_current_wave(self) -> WaveStatus:
        """Return the current wave status."""
        return self._current_status or WaveStatus(
            phase="Undetermined", label="N/A", sub_wave="N/A", confidence="Low"
        )

    def get_targets(self) -> List[dict]:
        """Return Fibonacci target zones."""
        return self._targets

    def get_invalidation_price(self) -> Optional[float]:
        """Return the price level that invalidates the current wave count."""
        return self._invalidation

    def get_wave_labels(self) -> List[dict]:
        """Return labelled wave pivots."""
        return [
            {"label": wl.label, "price": wl.price, "time": wl.time}
            for wl in self.wave_labels
        ]

    def summary(self) -> dict:
        """Return a full summary dict for LLM consumption."""
        status = self.identify_current_wave()
        return {
            "primary_structure": status.phase,
            "current_wave_label": status.label,
            "sub_wave_label": status.sub_wave,
            "confidence": status.confidence,
            "wave_pivots": self.get_wave_labels(),
            "target_fibonacci_zones": self.get_targets(),
            "invalidation_level": self.get_invalidation_price(),
            "total_zigzag_pivots": len(self.pivots),
        }
