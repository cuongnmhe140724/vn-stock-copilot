"""VNStock data service – fetches financial & price data for Vietnam stocks."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
from vnstock import Vnstock

logger = logging.getLogger(__name__)


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten MultiIndex columns to plain strings.

    vnstock DataFrames sometimes have tuple column names like
    ('ROE', 'Q1 2024') which break json serialization.
    """
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = ["_".join(str(c) for c in col).strip("_") for col in df.columns]
    else:
        # Even single-level columns can be tuples in some pandas versions
        df = df.copy()
        df.columns = [str(c) for c in df.columns]
    return df


# ── Financial data ───────────────────────────────────────────────────────────


def get_financial_ratios(ticker: str, periods: int = 8) -> dict[str, Any]:
    """Fetch key financial ratios (quarterly) for the given ticker.

    Returns a dict with keys: revenue_growth, profit_growth, roe, pe_ratio,
    debt_to_equity, raw_ratios (DataFrame as dict).
    """
    try:
        stock = Vnstock().stock(symbol=ticker, source="VCI")
        finance = stock.finance

        # Quarterly financial ratios
        ratios = finance.ratio(period="quarter", lang="en")
        if ratios is None or ratios.empty:
            return {"error": f"No financial ratio data found for {ticker}"}

        # Flatten MultiIndex columns & limit to recent periods
        ratios = _flatten_columns(ratios).tail(periods)

        # Income statement for growth calculation
        income = finance.income_statement(period="quarter", lang="en")
        if income is not None and not income.empty:
            income = _flatten_columns(income).tail(periods)

        result: dict[str, Any] = {
            "ticker": ticker,
            "raw_ratios": ratios.to_dict(orient="records"),
        }

        # Extract latest metrics from ratios
        latest = ratios.iloc[-1] if not ratios.empty else {}

        # ROE
        for col in ratios.columns:
            col_lower = str(col).lower()
            if "roe" in col_lower:
                result["roe"] = float(latest.get(col, 0))
                break
        else:
            result["roe"] = 0.0

        # P/E
        for col in ratios.columns:
            col_lower = str(col).lower()
            if "p/e" in col_lower or "pe" in col_lower:
                result["pe_ratio"] = float(latest.get(col, 0))
                break
        else:
            result["pe_ratio"] = 0.0

        # Debt-to-Equity
        for col in ratios.columns:
            col_lower = str(col).lower()
            if "debt" in col_lower and "equity" in col_lower:
                result["debt_to_equity"] = float(latest.get(col, 0))
                break
        else:
            result["debt_to_equity"] = 0.0

        # Revenue & Profit growth (YoY from income statement)
        if income is not None and len(income) >= 5:
            # Use specific column names to avoid matching "Revenue YoY (%)" etc.
            rev_col = _find_column(income, ["revenue (bn", "net sales", "doanh thu thuần"])
            if not rev_col:
                rev_col = _find_column_exclude(income, ["revenue", "doanh thu"], exclude=["yoy", "%"])
            profit_col = _find_column(income, ["net profit", "attributable to parent company (bn", "lợi nhuận ròng"])
            if not profit_col:
                profit_col = _find_column_exclude(income, ["profit", "loi nhuan"], exclude=["yoy", "%", "margin"])

            if rev_col:
                current_rev = income[rev_col].iloc[-1]
                prev_rev = income[rev_col].iloc[-4]  # same quarter last year
                result["revenue_growth"] = (
                    _safe_growth(current_rev, prev_rev)
                )
            else:
                result["revenue_growth"] = 0.0

            if profit_col:
                current_profit = income[profit_col].iloc[-1]
                prev_profit = income[profit_col].iloc[-4]
                result["profit_growth"] = (
                    _safe_growth(current_profit, prev_profit)
                )
            else:
                result["profit_growth"] = 0.0
        else:
            result["revenue_growth"] = 0.0
            result["profit_growth"] = 0.0

        return result

    except Exception as exc:
        logger.exception("Failed to fetch financial ratios for %s", ticker)
        return {"error": str(exc)}


def get_income_statement(ticker: str, periods: int = 8) -> dict[str, Any]:
    """Return recent income statement data as a list of dicts."""
    try:
        stock = Vnstock().stock(symbol=ticker, source="VCI")
        income = stock.finance.income_statement(period="quarter", lang="en")
        if income is None or income.empty:
            return {"error": f"No income statement data for {ticker}"}
        return {"ticker": ticker, "data": _flatten_columns(income).tail(periods).to_dict(orient="records")}
    except Exception as exc:
        logger.exception("Failed to fetch income statement for %s", ticker)
        return {"error": str(exc)}


# ── Price & Technical data ───────────────────────────────────────────────────


def get_price_history(
    ticker: str, days: int = 365
) -> pd.DataFrame | dict[str, str]:
    """Return OHLCV DataFrame for the last `days` trading days."""
    try:
        stock = Vnstock().stock(symbol=ticker, source="VCI")
        end = datetime.now()
        start = end - timedelta(days=days)

        df = stock.quote.history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
        )
        if df is None or df.empty:
            return {"error": f"No price data for {ticker}"}
        return _flatten_columns(df)

    except Exception as exc:
        logger.exception("Failed to fetch price history for %s", ticker)
        return {"error": str(exc)}


def get_current_price(ticker: str) -> dict[str, Any]:
    """Return the latest close price and basic info."""
    try:
        df = get_price_history(ticker, days=10)
        if isinstance(df, dict):
            return df  # error dict

        latest = df.iloc[-1]

        # Try to identify column names dynamically
        close_col = _find_column(df, ["close"])
        volume_col = _find_column(df, ["volume"])

        close = float(latest[close_col]) if close_col else 0.0
        volume = int(latest[volume_col]) if volume_col else 0

        prev = df.iloc[-2] if len(df) >= 2 else latest
        prev_close = float(prev[close_col]) if close_col else close
        change_pct = ((close - prev_close) / prev_close * 100) if prev_close else 0.0

        return {
            "ticker": ticker,
            "close": close,
            "volume": volume,
            "change_percent": round(change_pct, 2),
        }

    except Exception as exc:
        logger.exception("Failed to get current price for %s", ticker)
        return {"error": str(exc)}


def calculate_technical_indicators(df: pd.DataFrame) -> dict[str, Any]:
    """Compute MA50, MA200, RSI-14 from an OHLCV DataFrame.

    Returns a dict with trend, rsi, ma_alignment, support_zone, resistance_zone.
    """
    close_col = _find_column(df, ["close"])
    if not close_col:
        return {"error": "Cannot find 'close' column in DataFrame"}

    close = df[close_col].astype(float)

    # Moving Averages
    ma20 = close.rolling(20).mean()
    ma50 = close.rolling(50).mean()
    ma200 = close.rolling(200).mean()

    # RSI-14
    rsi = _compute_rsi(close, period=14)

    latest_close = close.iloc[-1]
    latest_ma50 = ma50.iloc[-1] if not np.isnan(ma50.iloc[-1]) else 0
    latest_ma200 = ma200.iloc[-1] if not np.isnan(ma200.iloc[-1]) else 0
    latest_ma20 = ma20.iloc[-1] if not np.isnan(ma20.iloc[-1]) else 0
    latest_rsi = rsi.iloc[-1] if not np.isnan(rsi.iloc[-1]) else 50

    # Trend determination
    if latest_ma50 > latest_ma200 and latest_close > latest_ma50:
        trend = "UP"
    elif latest_ma50 < latest_ma200 and latest_close < latest_ma50:
        trend = "DOWN"
    else:
        trend = "SIDEWAYS"

    # MA alignment description
    ma_parts = []
    if latest_ma20:
        ma_parts.append(f"MA20={latest_ma20:,.0f}")
    if latest_ma50:
        ma_parts.append(f"MA50={latest_ma50:,.0f}")
    if latest_ma200:
        ma_parts.append(f"MA200={latest_ma200:,.0f}")
    ma_alignment = " > ".join(ma_parts) if ma_parts else "N/A"

    # Simple support / resistance from recent lows / highs
    recent = df.tail(60)
    low_col = _find_column(df, ["low"])
    high_col = _find_column(df, ["high"])
    support = f"{recent[low_col].min():,.0f}" if low_col else "N/A"
    resistance = f"{recent[high_col].max():,.0f}" if high_col else "N/A"

    return {
        "trend": trend,
        "rsi": round(float(latest_rsi), 2),
        "ma_alignment": ma_alignment,
        "support_zone": support,
        "resistance_zone": resistance,
        "ma50": round(float(latest_ma50), 2),
        "ma200": round(float(latest_ma200), 2),
        "latest_close": round(float(latest_close), 2),
    }


# ── Helpers ──────────────────────────────────────────────────────────────────


def _find_column(df: pd.DataFrame, keywords: list[str]) -> str | None:
    """Find the first column name containing any of the keywords (case-insensitive)."""
    for col in df.columns:
        for kw in keywords:
            if kw.lower() in str(col).lower():
                return col
    return None


def _find_column_exclude(
    df: pd.DataFrame, keywords: list[str], exclude: list[str] | None = None
) -> str | None:
    """Find a column matching keywords but NOT containing any exclude patterns."""
    exclude = exclude or []
    for col in df.columns:
        col_str = str(col).lower()
        if any(kw.lower() in col_str for kw in keywords):
            if not any(ex.lower() in col_str for ex in exclude):
                return col
    return None


def _safe_growth(current: float, previous: float) -> float:
    """Calculate growth % safely."""
    try:
        if previous and previous != 0:
            return round(((current - previous) / abs(previous)) * 100, 2)
    except (TypeError, ZeroDivisionError):
        pass
    return 0.0


def _compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Compute RSI from a price series."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi
