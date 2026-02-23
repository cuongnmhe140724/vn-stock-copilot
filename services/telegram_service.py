"""Telegram Bot service – sends messages & reports to a Telegram chat."""

from __future__ import annotations

import logging

import httpx

from config import get_settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.telegram.org/bot{token}"


def _api_url(method: str) -> str:
    settings = get_settings()
    return f"{_BASE_URL.format(token=settings.telegram_bot_token)}/{method}"


async def send_message(text: str, parse_mode: str = "Markdown") -> bool:
    """Send a text message to the configured Telegram chat.

    Returns True on success.
    """
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.warning("Telegram credentials not configured – skipping send.")
        return False

    # Telegram has a 4096-char limit per message
    chunks = _split_message(text, max_len=4000)
    success = True

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            for chunk in chunks:
                resp = await client.post(
                    _api_url("sendMessage"),
                    json={
                        "chat_id": settings.telegram_chat_id,
                        "text": chunk,
                        "parse_mode": parse_mode,
                    },
                )
                if resp.status_code != 200:
                    logger.error("Telegram API error: %s", resp.text)
                    success = False
    except Exception as exc:
        logger.exception("Failed to send Telegram message: %s", exc)
        return False

    return success


def send_message_sync(text: str, parse_mode: str = "Markdown") -> bool:
    """Synchronous version of send_message."""
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.warning("Telegram credentials not configured – skipping send.")
        return False

    chunks = _split_message(text, max_len=4000)
    success = True

    try:
        with httpx.Client(timeout=15) as client:
            for chunk in chunks:
                resp = client.post(
                    _api_url("sendMessage"),
                    json={
                        "chat_id": settings.telegram_chat_id,
                        "text": chunk,
                        "parse_mode": parse_mode,
                    },
                )
                if resp.status_code != 200:
                    logger.error("Telegram API error: %s", resp.text)
                    success = False
    except Exception as exc:
        logger.exception("Failed to send Telegram message: %s", exc)
        return False

    return success


async def send_report(ticker: str, report: str) -> bool:
    """Format and send an analysis report for a specific ticker."""
    header = f"📊 *Báo cáo phân tích: {ticker}*\n{'─' * 30}\n\n"
    return await send_message(header + report)


def send_report_sync(ticker: str, report: str) -> bool:
    """Synchronous version of send_report."""
    header = f"📊 *Báo cáo phân tích: {ticker}*\n{'─' * 30}\n\n"
    return send_message_sync(header + report)


def _split_message(text: str, max_len: int = 4000) -> list[str]:
    """Split a long message into chunks that fit Telegram's limit."""
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Try to split at a newline near the limit
        split_idx = text.rfind("\n", 0, max_len)
        if split_idx == -1:
            split_idx = max_len
        chunks.append(text[:split_idx])
        text = text[split_idx:].lstrip("\n")

    return chunks
