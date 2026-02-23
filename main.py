"""FastAPI application – REST endpoints for the VN-Stock AI Copilot."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel

from agents.graph import run_analysis
from database import crud
from services.telegram_service import send_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-25s │ %(levelname)-7s │ %(message)s",
)
logger = logging.getLogger(__name__)


# ── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 VN-Stock AI Copilot starting up …")
    yield
    logger.info("👋 VN-Stock AI Copilot shutting down …")


app = FastAPI(
    title="VN-Stock AI Copilot",
    description="AI Agent hỗ trợ đầu tư chứng khoán Việt Nam",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Schemas ──────────────────────────────────────────────────────────────────

class WatchlistAddRequest(BaseModel):
    symbol: str
    initial_notes: str = ""

class AnalysisResponse(BaseModel):
    ticker: str
    report: str
    status: str = "success"


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "vn-stock-ai-copilot"}


@app.post("/analyze/{ticker}", response_model=AnalysisResponse)
async def analyze_ticker(ticker: str, background_tasks: BackgroundTasks):
    """Run on-demand deep analysis for a ticker (Workflow A).

    Returns the Markdown report and optionally sends it via Telegram.
    """
    ticker = ticker.upper()
    logger.info("📩 Received analysis request for %s", ticker)

    try:
        # Ensure stock exists in DB
        try:
            crud.upsert_stock(symbol=ticker)
        except Exception:
            logger.warning("Could not upsert stock to DB (DB might not be configured)")

        # Run the LangGraph pipeline
        result = run_analysis(ticker)
        report = result.get("final_message", "")

        # Send to Telegram in background
        background_tasks.add_task(send_report, ticker, report)

        return AnalysisResponse(ticker=ticker, report=report)

    except Exception as exc:
        logger.exception("Analysis failed for %s", ticker)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/watchlist")
async def add_watchlist(req: WatchlistAddRequest):
    """Add a ticker to the watchlist."""
    symbol = req.symbol.upper()
    try:
        # Ensure stock record exists
        crud.upsert_stock(symbol=symbol)
        item = crud.add_to_watchlist(symbol=symbol, initial_notes=req.initial_notes)
        return {"status": "added", "data": item}
    except Exception as exc:
        logger.exception("Failed to add %s to watchlist", symbol)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/watchlist")
async def list_watchlist():
    """List all active watchlist items."""
    try:
        items = crud.get_active_watchlist()
        return {"status": "ok", "count": len(items), "data": items}
    except Exception as exc:
        logger.exception("Failed to fetch watchlist")
        raise HTTPException(status_code=500, detail=str(exc))


@app.delete("/watchlist/{symbol}")
async def close_watchlist(symbol: str):
    """Mark a watchlist item as closed."""
    symbol = symbol.upper()
    try:
        success = crud.close_watchlist_item(symbol)
        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"No active watchlist item found for {symbol}",
            )
        return {"status": "closed", "symbol": symbol}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to close watchlist for %s", symbol)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/snapshots/{symbol}")
async def get_snapshots(symbol: str, limit: int = 30):
    """Get recent daily snapshots for a symbol."""
    try:
        data = crud.get_snapshots_by_symbol(symbol.upper(), limit=limit)
        return {"status": "ok", "count": len(data), "data": data}
    except Exception as exc:
        logger.exception("Failed to fetch snapshots for %s", symbol)
        raise HTTPException(status_code=500, detail=str(exc))
