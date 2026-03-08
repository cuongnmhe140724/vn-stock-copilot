"""Backtrader DataFeed adapter for vnstock DataFrames.

Maps vnstock column names (time, open, high, low, close, volume) to
Backtrader's expected fields.

Usage::

    import backtrader as bt
    from backtesting.data_feed import VnstockDataFeed

    cerebro = bt.Cerebro()
    cerebro.adddata(VnstockDataFeed(dataname=df))
"""

from __future__ import annotations

import logging

import backtrader as bt
import pandas as pd

logger = logging.getLogger(__name__)


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure DataFrame has Backtrader-compatible column names.

    vnstock returns lowercase columns and a ``time`` column for dates.
    Backtrader's ``PandasData`` expects a ``datetime`` column (or index).
    """
    df = df.copy()

    # Rename vnstock columns
    rename_map = {}
    for col in df.columns:
        lower = col.lower()
        if lower == "time":
            rename_map[col] = "datetime"
        elif lower == "date":
            rename_map[col] = "datetime"
        elif lower in ("open", "high", "low", "close", "volume"):
            rename_map[col] = lower
    df.rename(columns=rename_map, inplace=True)

    # Ensure datetime column is proper datetime type
    if "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"])

    return df


class VnstockDataFeed(bt.feeds.PandasData):
    """Backtrader DataFeed from a vnstock DataFrame.

    Automatically maps vnstock's column naming convention to what
    Backtrader expects.

    Parameters
    ----------
    dataname : pd.DataFrame
        A vnstock OHLCV DataFrame with columns like ``time``, ``open``,
        ``high``, ``low``, ``close``, ``volume``.
        The ``datetime`` column should already be set as the index.
    """

    params = (
        ("datetime", None),   # None = use the DataFrame index
        ("open", "open"),
        ("high", "high"),
        ("low", "low"),
        ("close", "close"),
        ("volume", "volume"),
        ("openinterest", None),
    )


def create_data_feed(df: pd.DataFrame, **kwargs) -> VnstockDataFeed:
    """Convenience factory to build a VnstockDataFeed from a DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        vnstock OHLCV data (must have time/open/high/low/close/volume columns).

    Returns
    -------
    VnstockDataFeed
        Ready-to-use Backtrader data feed.
    """
    normalised = _normalise_columns(df)

    # Set datetime as index — Backtrader reads dates from the index
    if "datetime" in normalised.columns:
        normalised = normalised.set_index("datetime")

    return VnstockDataFeed(dataname=normalised, **kwargs)
