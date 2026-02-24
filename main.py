"""FastAPI application – REST endpoints for the VN-Stock AI Copilot."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel, Field

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
    description=(
        "🇻🇳 **AI Agent hỗ trợ đầu tư chứng khoán Việt Nam**\n\n"
        "Phân tích chuyên sâu Fundamental & Technical, theo dõi biến động danh mục hàng ngày, "
        "đưa ra khuyến nghị **Buy / Hold / Sell** dựa trên chiến lược dài hạn.\n\n"
        "### Workflows\n"
        "- **On-demand Analysis**: Gọi `/analyze/{ticker}` để chạy full AI pipeline\n"
        "- **Daily Follow-up**: Worker tự động chạy lúc 15:45 hàng ngày\n\n"
        "### Tech Stack\n"
        "LangGraph + Claude 3.5 Sonnet · vnstock · Supabase · Telegram Bot"
    ),
    version="1.0.0",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "Analysis", "description": "AI-powered stock analysis (LangGraph pipeline)"},
        {"name": "Watchlist", "description": "Quản lý danh mục theo dõi"},
        {"name": "Snapshots", "description": "Lịch sử biến động hàng ngày"},
        {"name": "System", "description": "Health check & monitoring"},
    ],
    docs_url="/docs",
    redoc_url="/redoc",
)


# ── Schemas ──────────────────────────────────────────────────────────────────

class WatchlistAddRequest(BaseModel):
    symbol: str = Field(..., example="VNM", description="Mã cổ phiếu (HOSE/HNX/UPCOM)")
    initial_notes: str = Field(default="", example="Blue-chip ngành sữa", description="Ghi chú ban đầu")

    model_config = {"json_schema_extra": {"examples": [{"symbol": "VNM", "initial_notes": "Blue-chip ngành sữa"}]}}


class AnalysisResponse(BaseModel):
    ticker: str = Field(..., example="VNM", description="Mã cổ phiếu")
    report: str = Field(..., description="Báo cáo phân tích Markdown")
    status: str = Field(default="success", example="success")


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"], summary="Health Check")
async def health():
    """Kiểm tra trạng thái hoạt động của server."""
    return {"status": "ok", "service": "vn-stock-ai-copilot"}


@app.post("/analyze/{ticker}", response_model=AnalysisResponse, tags=["Analysis"], summary="Phân tích mã cổ phiếu")
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


@app.post("/watchlist", tags=["Watchlist"], summary="Thêm mã vào watchlist")
async def add_watchlist(req: WatchlistAddRequest):
    """Thêm một mã cổ phiếu vào danh mục theo dõi (status = active)."""
    symbol = req.symbol.upper()
    try:
        # Ensure stock record exists
        crud.upsert_stock(symbol=symbol)
        item = crud.add_to_watchlist(symbol=symbol, initial_notes=req.initial_notes)
        return {"status": "added", "data": item}
    except Exception as exc:
        logger.exception("Failed to add %s to watchlist", symbol)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/watchlist", tags=["Watchlist"], summary="Xem danh mục theo dõi")
async def list_watchlist():
    """Liệt kê tất cả mã đang active trong watchlist."""
    try:
        items = crud.get_active_watchlist()
        return {"status": "ok", "count": len(items), "data": items}
    except Exception as exc:
        logger.exception("Failed to fetch watchlist")
        raise HTTPException(status_code=500, detail=str(exc))


@app.delete("/watchlist/{symbol}", tags=["Watchlist"], summary="Đóng mã khỏi watchlist")
async def close_watchlist(symbol: str):
    """Đánh dấu một mã là 'closed' — không còn theo dõi hàng ngày."""
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


@app.get("/snapshots/{symbol}", tags=["Snapshots"], summary="Lịch sử biến động")
async def get_snapshots(
    symbol: str,
    limit: int = Query(default=30, ge=1, le=365, description="Số phiên gần nhất"),
):
    """Lấy lịch sử daily snapshots (giá, volume, AI commentary, tín hiệu) cho một mã."""
    try:
        data = crud.get_snapshots_by_symbol(symbol.upper(), limit=limit)
        return {"status": "ok", "count": len(data), "data": data}
    except Exception as exc:
        logger.exception("Failed to fetch snapshots for %s", symbol)
        raise HTTPException(status_code=500, detail=str(exc))
