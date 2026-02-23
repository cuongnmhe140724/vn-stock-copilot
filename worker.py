"""Daily cron worker – runs at 15:45 GMT+7 to follow up on watchlist.

Usage:
    python worker.py          # starts the scheduler (blocks)
    python worker.py --once   # runs the job once and exits
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from config import get_settings
from database import crud
from prompts.system_prompts import DAILY_FOLLOWUP_PROMPT
from services import vnstock_service
from services.telegram_service import send_message_sync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-25s │ %(levelname)-7s │ %(message)s",
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Core job logic
# ─────────────────────────────────────────────────────────────────────────────


def daily_followup_job() -> None:
    """Follow up on every active watchlist symbol."""

    logger.info("⏰ Daily follow-up job triggered at %s", datetime.now())

    try:
        watchlist = crud.get_active_watchlist()
    except Exception as exc:
        logger.error("Cannot fetch watchlist: %s", exc)
        send_message_sync("❌ *Daily Job Error*: Không thể truy cập watchlist.")
        return

    if not watchlist:
        logger.info("Watchlist is empty – nothing to do.")
        return

    all_reports: list[str] = []
    settings = get_settings()

    for item in watchlist:
        symbol = item["symbol"]
        logger.info("📌 Processing %s …", symbol)

        try:
            report = _process_symbol(symbol, settings)
            all_reports.append(report)
        except Exception as exc:
            logger.exception("Failed to process %s", symbol)
            all_reports.append(f"❌ {symbol}: Lỗi – {exc}")

    # Combine and send summary
    today = datetime.now().strftime("%d/%m/%Y")
    header = f"📋 *Daily Watchlist Report — {today}*\n{'─' * 35}\n\n"
    full_report = header + "\n\n".join(all_reports)

    send_message_sync(full_report)
    logger.info("✅ Daily follow-up completed – %d symbols processed.", len(watchlist))


def _process_symbol(symbol: str, settings) -> str:
    """Process a single symbol: fetch data, compare thesis, generate alert."""

    # 1. Get current market data
    price_info = vnstock_service.get_current_price(symbol)
    if "error" in price_info:
        return f"⚠️ *{symbol}*: Không lấy được dữ liệu giá – {price_info['error']}"

    close_price = price_info["close"]
    volume = price_info["volume"]
    change_pct = price_info["change_percent"]

    # 2. Get stored thesis
    thesis = crud.get_latest_thesis(symbol)

    # 3. Decision tree
    signal = "HOLD"
    emoji = "⚪"
    note = "Luận điểm chưa thay đổi, tiếp tục theo dõi."

    if thesis:
        stop_loss = thesis.get("stop_loss_price") or 0
        entry_min = thesis.get("entry_zone_min") or 0
        entry_max = thesis.get("entry_zone_max") or float("inf")
        target = thesis.get("target_price") or float("inf")

        if stop_loss and close_price <= stop_loss:
            signal = "SELL"
            emoji = "🔴"
            note = f"CẮT LỖ NGAY – Giá {close_price:,.0f} đã phá vỡ stop-loss {stop_loss:,.0f}"
        elif entry_min and entry_max and entry_min <= close_price <= entry_max:
            signal = "BUY_MORE"
            emoji = "🟢"
            note = f"ĐIỂM MUA ĐẸP – Giá {close_price:,.0f} nằm trong vùng entry [{entry_min:,.0f} – {entry_max:,.0f}]"
        elif target and close_price >= target:
            signal = "SELL"
            emoji = "🟡"
            note = f"CHỐT LỜI MỘT PHẦN – Giá {close_price:,.0f} đã đạt target {target:,.0f}"
        else:
            signal = "HOLD"
            emoji = "⚪"
            note = "GIỮ – Luận điểm chưa thay đổi, tiếp tục theo dõi."

    # 4. AI commentary via Claude (optional, graceful fallback)
    ai_comment = ""
    try:
        ai_comment = _get_ai_commentary(symbol, close_price, change_pct, volume, thesis, settings)
    except Exception:
        logger.warning("AI commentary skipped for %s", symbol)

    # 5. Save snapshot to DB
    try:
        crud.insert_snapshot(
            symbol=symbol,
            close_price=close_price,
            volume=volume,
            change_percent=change_pct,
            ai_commentary=ai_comment or note,
            action_signal=signal,
        )
    except Exception:
        logger.warning("Could not save snapshot for %s", symbol)

    # 6. Format report section
    report = (
        f"{emoji} *{symbol}*\n"
        f"├ Giá: {close_price:,.0f} ({change_pct:+.2f}%)\n"
        f"├ Volume: {volume:,}\n"
        f"├ Tín hiệu: *{signal}*\n"
        f"└ {note}"
    )

    if ai_comment:
        report += f"\n💬 _{ai_comment[:200]}_"

    return report


def _get_ai_commentary(
    symbol: str,
    close_price: float,
    change_pct: float,
    volume: int,
    thesis: dict | None,
    settings,
) -> str:
    """Get a short AI commentary using Claude."""
    llm = ChatAnthropic(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key,
        max_tokens=500,
        temperature=0.3,
    )

    thesis_text = ""
    if thesis:
        thesis_text = (
            f"Target: {thesis.get('target_price', 'N/A')}, "
            f"Stop-loss: {thesis.get('stop_loss_price', 'N/A')}, "
            f"Entry: [{thesis.get('entry_zone_min', 'N/A')} – {thesis.get('entry_zone_max', 'N/A')}]"
        )

    data = (
        f"Symbol: {symbol}\n"
        f"Close: {close_price:,.0f} | Change: {change_pct:+.2f}% | Volume: {volume:,}\n"
        f"Thesis: {thesis_text}\n"
    )

    messages = [
        SystemMessage(content=DAILY_FOLLOWUP_PROMPT),
        HumanMessage(content=data),
    ]

    response = llm.invoke(messages)
    return response.content.strip()[:300]


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--once" in sys.argv:
        logger.info("Running daily follow-up job once …")
        daily_followup_job()
    else:
        logger.info("Starting scheduler – daily job at 15:45 (Asia/Ho_Chi_Minh)")
        scheduler = BlockingScheduler(timezone="Asia/Ho_Chi_Minh")
        scheduler.add_job(
            daily_followup_job,
            trigger=CronTrigger(hour=15, minute=45),
            id="daily_followup",
            name="Daily Watchlist Follow-up (15:45 VN)",
        )
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler stopped.")
