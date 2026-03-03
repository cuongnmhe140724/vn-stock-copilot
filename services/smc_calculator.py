"""Smart Money Concepts (SMC) calculator.

Provides:
  - Swing High / Swing Low detection (sliding-window fractals)
  - BOS (Break of Structure) / CHoCH (Change of Character)
  - FVG (Fair Value Gap) detection
  - Order Block identification
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, List, Literal

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class SwingPoint:
    index: int
    price: float
    type: Literal["high", "low"]
    time: Any = None


@dataclass
class StructureBreak:
    """A BOS or CHoCH event."""
    index: int
    break_type: Literal["BOS", "CHoCH"]
    direction: Literal["bullish", "bearish"]
    level: float  # the swing level that was broken
    time: Any = None


@dataclass
class FVG:
    """Fair Value Gap (imbalance)."""
    index: int  # index of the middle candle
    direction: Literal["bullish", "bearish"]
    top: float
    bottom: float
    filled: bool = False
    time: Any = None


@dataclass
class OrderBlock:
    index: int
    direction: Literal["bullish", "bearish"]
    top: float
    bottom: float
    mitigated: bool = False
    time: Any = None


# ── Main calculator ──────────────────────────────────────────────────────────

class SMCCalculator:
    """Compute SMC structures from an OHLCV DataFrame.

    Expected columns (case-insensitive matching): open, high, low, close, volume.
    The DataFrame must be sorted ascending by time (oldest first).
    """

    def __init__(self, df: pd.DataFrame, swing_window: int = 2) -> None:
        self.df = df.copy().reset_index(drop=True)
        self.swing_window = swing_window

        # Resolve column names
        self._open = self._col("open")
        self._high = self._col("high")
        self._low = self._col("low")
        self._close = self._col("close")
        self._volume = self._col("volume")
        self._time = self._col("time") or self._col("date")

        # Pre-compute
        self.swing_points: List[SwingPoint] = []
        self.structure_breaks: List[StructureBreak] = []
        self.fvg_list: List[FVG] = []
        self.order_blocks: List[OrderBlock] = []

        self._compute_all()

    # ── Column resolution ────────────────────────────────────────────────

    def _col(self, keyword: str) -> str | None:
        for c in self.df.columns:
            if keyword.lower() in str(c).lower():
                return c
        return None

    # ── Master compute ───────────────────────────────────────────────────

    def _compute_all(self) -> None:
        self.find_swing_points()
        self.detect_bos_choch()
        self.detect_fvg()
        self.detect_order_blocks()
        self._check_ob_mitigation()

    # ── 1. Swing Points (Fractals) ───────────────────────────────────────

    def find_swing_points(self) -> List[SwingPoint]:
        """Sliding-window fractal detection.

        A bar is a Swing High if its high is the highest within `window` bars
        on each side.  Likewise for Swing Low.
        """
        highs = self.df[self._high].values.astype(float)
        lows = self.df[self._low].values.astype(float)
        n = len(self.df)
        w = self.swing_window
        self.swing_points = []

        for i in range(w, n - w):
            # Swing High check
            is_sh = True
            for j in range(1, w + 1):
                if highs[i] <= highs[i - j] or highs[i] <= highs[i + j]:
                    is_sh = False
                    break
            if is_sh:
                t = self.df[self._time].iloc[i] if self._time else None
                self.swing_points.append(
                    SwingPoint(index=i, price=highs[i], type="high", time=t)
                )

            # Swing Low check
            is_sl = True
            for j in range(1, w + 1):
                if lows[i] >= lows[i - j] or lows[i] >= lows[i + j]:
                    is_sl = False
                    break
            if is_sl:
                t = self.df[self._time].iloc[i] if self._time else None
                self.swing_points.append(
                    SwingPoint(index=i, price=lows[i], type="low", time=t)
                )

        # Sort by index
        self.swing_points.sort(key=lambda sp: sp.index)
        return self.swing_points

    # ── 2. BOS / CHoCH ──────────────────────────────────────────────────

    def detect_bos_choch(self) -> List[StructureBreak]:
        """Detect Break of Structure / Change of Character.

        Walk through swing points tracking the *current bias* (bullish /
        bearish).  When close breaks the nearest swing:
          - Same direction as bias → BOS (continuation)
          - Opposite direction     → CHoCH (reversal)
        """
        closes = self.df[self._close].values.astype(float)
        self.structure_breaks = []

        if len(self.swing_points) < 2:
            return self.structure_breaks

        # Initial bias: if first two swings are Low then High → bullish
        bias: Literal["bullish", "bearish"] = "bullish"
        if self.swing_points[0].type == "high":
            bias = "bearish"

        last_sh: SwingPoint | None = None
        last_sl: SwingPoint | None = None

        for sp in self.swing_points:
            if sp.type == "high":
                last_sh = sp
            else:
                last_sl = sp

            if last_sh is None or last_sl is None:
                continue

            # Check candles AFTER this swing point for break
            start_idx = sp.index + 1
            end_idx = min(sp.index + 10, len(closes))  # look-ahead window

            for ci in range(start_idx, end_idx):
                # Bullish break: close > last Swing High
                if last_sh and closes[ci] > last_sh.price:
                    direction: Literal["bullish", "bearish"] = "bullish"
                    break_type: Literal["BOS", "CHoCH"] = (
                        "BOS" if bias == "bullish" else "CHoCH"
                    )
                    t = self.df[self._time].iloc[ci] if self._time else None
                    self.structure_breaks.append(
                        StructureBreak(
                            index=ci,
                            break_type=break_type,
                            direction=direction,
                            level=last_sh.price,
                            time=t,
                        )
                    )
                    bias = "bullish"
                    last_sh = None  # consumed
                    break

                # Bearish break: close < last Swing Low
                if last_sl and closes[ci] < last_sl.price:
                    direction = "bearish"
                    break_type = "BOS" if bias == "bearish" else "CHoCH"
                    t = self.df[self._time].iloc[ci] if self._time else None
                    self.structure_breaks.append(
                        StructureBreak(
                            index=ci,
                            break_type=break_type,
                            direction=direction,
                            level=last_sl.price,
                            time=t,
                        )
                    )
                    bias = "bearish"
                    last_sl = None  # consumed
                    break

        return self.structure_breaks

    # ── 3. Fair Value Gap ────────────────────────────────────────────────

    def detect_fvg(self) -> List[FVG]:
        """Detect Fair Value Gaps (3-candle imbalances).

        Bullish FVG:  low of candle [i-1]  >  high of candle [i+1]
        Bearish FVG:  high of candle [i-1] <  low of candle [i+1]
        """
        highs = self.df[self._high].values.astype(float)
        lows = self.df[self._low].values.astype(float)
        n = len(self.df)
        self.fvg_list = []

        for i in range(1, n - 1):
            t = self.df[self._time].iloc[i] if self._time else None

            # Bullish FVG: gap up
            if lows[i - 1] > highs[i + 1]:
                self.fvg_list.append(FVG(
                    index=i,
                    direction="bullish",
                    top=float(lows[i - 1]),
                    bottom=float(highs[i + 1]),
                    time=t,
                ))

            # Bearish FVG: gap down
            if highs[i - 1] < lows[i + 1]:
                self.fvg_list.append(FVG(
                    index=i,
                    direction="bearish",
                    top=float(lows[i + 1]),
                    bottom=float(highs[i - 1]),
                    time=t,
                ))

        # Mark filled FVGs
        closes = self.df[self._close].values.astype(float)
        for fvg in self.fvg_list:
            for j in range(fvg.index + 2, n):
                if fvg.direction == "bullish" and closes[j] <= fvg.bottom:
                    fvg.filled = True
                    break
                if fvg.direction == "bearish" and closes[j] >= fvg.top:
                    fvg.filled = True
                    break

        return self.fvg_list

    # ── 4. Order Blocks ─────────────────────────────────────────────────

    def detect_order_blocks(self) -> List[OrderBlock]:
        """Detect Order Blocks.

        Bullish OB: The last *bearish* candle before an impulsive *bullish*
        move that creates a BOS (breaks a Swing High) and ideally leaves an FVG.

        Bearish OB: The last *bullish* candle before an impulsive *bearish*
        move that creates a BOS (breaks a Swing Low).
        """
        opens = self.df[self._open].values.astype(float)
        closes = self.df[self._close].values.astype(float)
        highs = self.df[self._high].values.astype(float)
        lows = self.df[self._low].values.astype(float)
        self.order_blocks = []

        bos_indices = {sb.index: sb for sb in self.structure_breaks if sb.break_type == "BOS"}

        for idx, sb in bos_indices.items():
            t = self.df[self._time].iloc[idx] if self._time else None

            if sb.direction == "bullish":
                # Walk backwards to find the last bearish candle
                for k in range(idx - 1, max(idx - 15, -1), -1):
                    if closes[k] < opens[k]:  # bearish candle
                        self.order_blocks.append(OrderBlock(
                            index=k,
                            direction="bullish",
                            top=float(highs[k]),
                            bottom=float(lows[k]),
                            time=t,
                        ))
                        break

            elif sb.direction == "bearish":
                # Walk backwards to find the last bullish candle
                for k in range(idx - 1, max(idx - 15, -1), -1):
                    if closes[k] > opens[k]:  # bullish candle
                        self.order_blocks.append(OrderBlock(
                            index=k,
                            direction="bearish",
                            top=float(highs[k]),
                            bottom=float(lows[k]),
                            time=t,
                        ))
                        break

        return self.order_blocks

    # ── OB Mitigation check ──────────────────────────────────────────────

    def _check_ob_mitigation(self) -> None:
        """Mark OBs as mitigated if price has revisited the zone."""
        closes = self.df[self._close].values.astype(float)
        lows = self.df[self._low].values.astype(float)
        highs = self.df[self._high].values.astype(float)
        n = len(closes)

        for ob in self.order_blocks:
            for j in range(ob.index + 1, n):
                if ob.direction == "bullish" and lows[j] <= ob.bottom:
                    ob.mitigated = True
                    break
                if ob.direction == "bearish" and highs[j] >= ob.top:
                    ob.mitigated = True
                    break

    # ── Public API ───────────────────────────────────────────────────────

    def get_trend(self) -> str:
        """Return 'Bullish' or 'Bearish' based on the latest structure break."""
        if not self.structure_breaks:
            return "Neutral"
        latest = self.structure_breaks[-1]
        return "Bullish" if latest.direction == "bullish" else "Bearish"

    def get_latest_choch(self) -> dict | None:
        """Return the most recent CHoCH event, or None."""
        chochs = [sb for sb in self.structure_breaks if sb.break_type == "CHoCH"]
        if not chochs:
            return None
        ch = chochs[-1]
        return {
            "level": ch.level,
            "direction": ch.direction,
            "time": str(ch.time) if ch.time else None,
        }

    def get_unmitigated_ob(self, ob_type: str = "bullish") -> List[dict]:
        """Return unmitigated Order Blocks of the given type."""
        return [
            {"top": ob.top, "bottom": ob.bottom, "time": str(ob.time) if ob.time else None}
            for ob in self.order_blocks
            if ob.direction == ob_type and not ob.mitigated
        ]

    def get_fvg(self) -> List[dict]:
        """Return unfilled FVGs."""
        return [
            {
                "direction": fvg.direction,
                "top": fvg.top,
                "bottom": fvg.bottom,
                "time": str(fvg.time) if fvg.time else None,
            }
            for fvg in self.fvg_list
            if not fvg.filled
        ]

    def summary(self) -> dict:
        """Return a full SMC summary dict suitable for LLM consumption."""
        return {
            "current_trend": self.get_trend(),
            "recent_choch": self.get_latest_choch(),
            "active_bullish_order_blocks": self.get_unmitigated_ob("bullish"),
            "active_bearish_order_blocks": self.get_unmitigated_ob("bearish"),
            "unfilled_fvg": self.get_fvg(),
            "total_swing_points": len(self.swing_points),
            "total_structure_breaks": len(self.structure_breaks),
        }
