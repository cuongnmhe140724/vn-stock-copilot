"""LangChain tools for advanced technical analysis.

Three tools the analyst ReAct agent can call:
  1. get_smc_structures  – Smart Money Concepts (Order Blocks, FVG, BOS/CHoCH)
  2. analyze_elliott_waves – Elliott Wave position & targets
  3. analyze_wyckoff       – Wyckoff phases & Volume Profile
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool

from services import vnstock_service
from services.smc_calculator import SMCCalculator
from services.elliott_engine import ElliottWaveEngine
from services.wyckoff_engine import WyckoffEngine

logger = logging.getLogger(__name__)


def _fetch_ohlcv(ticker: str, days: int = 365):
    """Fetch OHLCV DataFrame via vnstock, return (df, error_dict)."""
    df = vnstock_service.get_price_history(ticker, days=days)
    if isinstance(df, dict):
        return None, df  # error
    if df is None or df.empty:
        return None, {"error": f"No OHLCV data for {ticker}"}
    return df, None


# ── Tool 1: SMC ─────────────────────────────────────────────────────────────

@tool
def get_smc_structures(
    ticker: str,
    lookback: int = 100,
) -> dict:
    """Tìm các vùng Order Block, FVG (Fair Value Gap), và trạng thái cấu trúc
    BOS/CHoCH của một mã chứng khoán.

    Sử dụng tool này để xác định Demand/Supply zones (vùng cung/cầu) nhằm
    tìm điểm mua/bán chính xác theo phương pháp Smart Money Concepts.

    Args:
        ticker: Mã chứng khoán (ví dụ: FPT, VCB, VNM)
        lookback: Số nến gần nhất để phân tích (mặc định 100)
    """
    try:
        df, err = _fetch_ohlcv(ticker, days=max(lookback * 2, 365))
        if err:
            return {"error": err.get("error", "Unknown error")}

        # Use up to `lookback` most recent bars
        df = df.tail(lookback).reset_index(drop=True)
        smc = SMCCalculator(df)
        return smc.summary()

    except Exception as exc:
        logger.exception("SMC tool failed for %s", ticker)
        return {"error": str(exc)}


# ── Tool 2: Elliott Wave ─────────────────────────────────────────────────────

@tool
def analyze_elliott_waves(
    ticker: str,
    zigzag_pct: float = 0.05,
) -> dict:
    """Xác định vị trí sóng Elliott hiện tại (Impulse 1-5 hoặc Correction A-B-C),
    kèm mục tiêu Fibonacci và mức giá phá vỡ kịch bản (invalidation).

    Sử dụng tool này để biết thị trường đang ở giai đoạn đẩy (impulse) hay
    điều chỉnh (correction) và dự kiến mục tiêu tiếp theo.

    Args:
        ticker: Mã chứng khoán (ví dụ: FPT, VCB, VNM)
        zigzag_pct: Ngưỡng lọc nhiễu ZigZag, 0.05 = 5% (mặc định)
    """
    try:
        df, err = _fetch_ohlcv(ticker, days=500)
        if err:
            return {"error": err.get("error", "Unknown error")}

        # Elliott needs longer history
        df = df.tail(200).reset_index(drop=True)
        engine = ElliottWaveEngine(df, zigzag_threshold=zigzag_pct)
        return engine.summary()

    except Exception as exc:
        logger.exception("Elliott Wave tool failed for %s", ticker)
        return {"error": str(exc)}


# ── Tool 3: Wyckoff ─────────────────────────────────────────────────────────

@tool
def analyze_wyckoff(
    ticker: str,
    lookback: int = 200,
) -> dict:
    """Phân tích Wyckoff: xác định giai đoạn tích lũy (Accumulation), phân phối
    (Distribution), tăng giá (Markup) hay giảm giá (Markdown).

    Bao gồm Volume Profile (khối lượng tại từng mức giá), Point of Control (POC),
    Value Area, và Trading Range (biên trên AR / biên dưới SC).

    Args:
        ticker: Mã chứng khoán (ví dụ: FPT, VCB, VNM)
        lookback: Số nến gần nhất để phân tích (mặc định 200)
    """
    try:
        df, err = _fetch_ohlcv(ticker, days=max(lookback * 2, 500))
        if err:
            return {"error": err.get("error", "Unknown error")}

        df = df.tail(lookback).reset_index(drop=True)
        engine = WyckoffEngine(df)
        return engine.summary()

    except Exception as exc:
        logger.exception("Wyckoff tool failed for %s", ticker)
        return {"error": str(exc)}


# ── All tools list (for agent setup) ────────────────────────────────────────

ANALYST_TOOLS = [get_smc_structures, analyze_elliott_waves, analyze_wyckoff]
