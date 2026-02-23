"""CRUD operations for all database tables."""

from __future__ import annotations

import logging
from datetime import datetime, date
from typing import Any, Optional

from database.supabase_client import get_supabase

logger = logging.getLogger(__name__)


# ── Stocks ───────────────────────────────────────────────────────────────────


def upsert_stock(
    symbol: str,
    company_name: str = "",
    industry: str = "",
    exchange: str = "HOSE",
) -> dict[str, Any]:
    """Insert or update a stock record."""
    db = get_supabase()
    data = {
        "symbol": symbol.upper(),
        "company_name": company_name,
        "industry": industry,
        "exchange": exchange,
    }
    result = db.table("stocks").upsert(data, on_conflict="symbol").execute()
    return result.data[0] if result.data else data


def get_stock(symbol: str) -> Optional[dict[str, Any]]:
    """Get a single stock by symbol."""
    db = get_supabase()
    result = db.table("stocks").select("*").eq("symbol", symbol.upper()).execute()
    return result.data[0] if result.data else None


# ── Watchlist ────────────────────────────────────────────────────────────────


def add_to_watchlist(
    symbol: str, initial_notes: str = ""
) -> dict[str, Any]:
    """Add a symbol to the active watchlist."""
    db = get_supabase()
    data = {
        "symbol": symbol.upper(),
        "status": "active",
        "initial_notes": initial_notes,
    }
    result = db.table("watchlist").insert(data).execute()
    return result.data[0] if result.data else data


def get_active_watchlist() -> list[dict[str, Any]]:
    """Return all watchlist entries with status='active'."""
    db = get_supabase()
    result = (
        db.table("watchlist")
        .select("*, stocks(company_name, industry, exchange)")
        .eq("status", "active")
        .order("added_at", desc=True)
        .execute()
    )
    return result.data or []


def close_watchlist_item(symbol: str) -> bool:
    """Mark a watchlist item as 'closed'."""
    db = get_supabase()
    result = (
        db.table("watchlist")
        .update({"status": "closed"})
        .eq("symbol", symbol.upper())
        .eq("status", "active")
        .execute()
    )
    return bool(result.data)


# ── Investment Theses ────────────────────────────────────────────────────────


def upsert_thesis(
    symbol: str,
    thesis_content: str,
    intrinsic_value: float = 0,
    target_price: float = 0,
    stop_loss_price: float = 0,
    entry_zone_min: float = 0,
    entry_zone_max: float = 0,
    sentiment_score: float = 0.5,
) -> dict[str, Any]:
    """Insert or update an investment thesis for a symbol."""
    db = get_supabase()
    data = {
        "symbol": symbol.upper(),
        "thesis_content": thesis_content,
        "intrinsic_value": intrinsic_value,
        "target_price": target_price,
        "stop_loss_price": stop_loss_price,
        "entry_zone_min": entry_zone_min,
        "entry_zone_max": entry_zone_max,
        "sentiment_score": sentiment_score,
        "last_updated": datetime.utcnow().isoformat(),
    }
    result = db.table("investment_theses").insert(data).execute()
    return result.data[0] if result.data else data


def get_latest_thesis(symbol: str) -> Optional[dict[str, Any]]:
    """Get the most recent investment thesis for a symbol."""
    db = get_supabase()
    result = (
        db.table("investment_theses")
        .select("*")
        .eq("symbol", symbol.upper())
        .order("last_updated", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


# ── Daily Snapshots ──────────────────────────────────────────────────────────


def insert_snapshot(
    symbol: str,
    close_price: float,
    volume: int,
    change_percent: float,
    ai_commentary: str = "",
    action_signal: str = "HOLD",
    snapshot_date: Optional[date] = None,
) -> dict[str, Any]:
    """Insert a daily snapshot for a symbol."""
    db = get_supabase()
    data = {
        "symbol": symbol.upper(),
        "date": (snapshot_date or date.today()).isoformat(),
        "close_price": close_price,
        "volume": volume,
        "change_percent": change_percent,
        "ai_commentary": ai_commentary,
        "action_signal": action_signal,
    }
    result = (
        db.table("daily_snapshots")
        .upsert(data, on_conflict="symbol,date")
        .execute()
    )
    return result.data[0] if result.data else data


def get_snapshots_by_symbol(
    symbol: str, limit: int = 30
) -> list[dict[str, Any]]:
    """Get recent daily snapshots for a symbol."""
    db = get_supabase()
    result = (
        db.table("daily_snapshots")
        .select("*")
        .eq("symbol", symbol.upper())
        .order("date", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []
