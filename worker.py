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
    """Process a single symbol: fetch data, compare thesis & scenarios, generate alert."""

    # 1. Get current market data
    price_info = vnstock_service.get_current_price(symbol)
    if "error" in price_info:
        return f"⚠️ *{symbol}*: Không lấy được dữ liệu giá – {price_info['error']}"

    close_price = price_info["close"]
    volume = price_info["volume"]
    change_pct = price_info["change_percent"]

    # 2. Get stored thesis & scenarios
    thesis = crud.get_latest_thesis(symbol)

    # 3. Load and evaluate scenarios
    scenarios = []
    primary_scenario = None
    primary_label = None
    if thesis:
        raw = thesis.get("scenarios_json", "[]")
        try:
            scenarios = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except Exception:
            scenarios = []
        primary_label = thesis.get("primary_scenario", "BASE")
        # Find the primary scenario object
        for s in scenarios:
            if s.get("label") == primary_label:
                primary_scenario = s
                break

    # 4. Scenario-aware decision
    signal = "HOLD"
    emoji = "⚪"
    note = "GIỮ — Kịch bản vẫn hiệu lực, tiếp tục theo dõi."
    needs_reanalysis = False

    if primary_scenario:
        # Use primary scenario's entry/target/stop-loss
        entry_range = primary_scenario.get("entry_range", [])
        entry_min = entry_range[0] if len(entry_range) > 0 else 0
        entry_max = entry_range[1] if len(entry_range) > 1 else float("inf")
        target = primary_scenario.get("target_price", 0)
        stop = primary_scenario.get("stop_loss", 0)

        # Check invalidation (parse price from invalidation text — fallback to stop)
        if stop and close_price <= stop:
            signal = "SELL"
            emoji = "🔴"
            note = f"KỊCH BẢN {primary_label} BỊ PHÁ VỠ — Giá {close_price:,.0f} < stop-loss {stop:,.0f}"
            needs_reanalysis = True
        elif entry_min and entry_max and entry_min <= close_price <= entry_max:
            signal = "BUY_MORE"
            emoji = "🟢"
            note = f"ĐIỂM MUA THEO KỊCH BẢN {primary_label} — Giá {close_price:,.0f} trong vùng [{entry_min:,.0f} – {entry_max:,.0f}]"
        elif target and close_price >= target:
            signal = "SELL"
            emoji = "🟡"
            note = f"CHỐT LỜI — Giá {close_price:,.0f} đạt target {target:,.0f} (kịch bản {primary_label})"
        else:
            signal = "HOLD"
            emoji = "⚪"
            note = f"GIỮ — Kịch bản {primary_label} vẫn hiệu lực."

    elif thesis:
        # Fallback: use thesis-level entry/target/stop (backward compat)
        stop_loss = thesis.get("stop_loss_price") or 0
        entry_min = thesis.get("entry_zone_min") or 0
        entry_max = thesis.get("entry_zone_max") or float("inf")
        target = thesis.get("target_price") or float("inf")

        if stop_loss and close_price <= stop_loss:
            signal = "SELL"
            emoji = "🔴"
            note = f"CẮT LỖ — Giá {close_price:,.0f} phá stop-loss {stop_loss:,.0f}"
        elif entry_min and entry_max and entry_min <= close_price <= entry_max:
            signal = "BUY_MORE"
            emoji = "🟢"
            note = f"ĐIỂM MUA — Giá {close_price:,.0f} trong entry [{entry_min:,.0f} – {entry_max:,.0f}]"
        elif target and close_price >= target:
            signal = "SELL"
            emoji = "🟡"
            note = f"CHỐT LỜI — Giá {close_price:,.0f} đạt target {target:,.0f}"

    # Check for re-analysis trigger
    if needs_reanalysis:
        emoji = "🟣"
        signal = "REANALYZE"
        note += " → CẦN PHÂN TÍCH LẠI TOÀN BỘ"

    # 5. AI commentary via Claude (optional, graceful fallback)
    ai_comment = ""
    try:
        ai_comment = _get_ai_commentary(
            symbol, close_price, change_pct, volume, thesis, scenarios, primary_label, settings
        )
    except Exception:
        logger.warning("AI commentary skipped for %s", symbol)

    # 6. Save snapshot to DB
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

    # 7. Format report section
    report = (
        f"{emoji} *{symbol}*\n"
        f"├ Giá: {close_price:,.0f} ({change_pct:+.2f}%)\n"
        f"├ Volume: {volume:,}\n"
        f"├ Kịch bản chính: *{primary_label or 'N/A'}*\n"
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
    scenarios: list | None,
    primary_label: str | None,
    settings,
) -> str:
    """Get a short AI commentary using Claude with scenario context."""
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

    # Build scenario context for the AI
    scenario_text = ""
    if scenarios:
        scenario_lines = []
        for s in scenarios:
            status = s.get("status", "ACTIVE")
            label = s.get("label", "?")
            prob = s.get("probability", "?")
            trigger = s.get("trigger", "N/A")
            scenario_lines.append(f"- {label} ({prob}%, {status}): trigger={trigger}")
        scenario_text = "\n".join(scenario_lines)

    data = (
        f"Symbol: {symbol}\n"
        f"Close: {close_price:,.0f} | Change: {change_pct:+.2f}% | Volume: {volume:,}\n"
        f"Thesis: {thesis_text}\n"
        f"Primary Scenario: {primary_label or 'N/A'}\n"
        f"Scenarios:\n{scenario_text}\n"
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
