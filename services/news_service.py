"""News service – searches for recent news headlines related to a ticker."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Google Custom Search fallback / simple scrape approach
_SEARCH_URL = "https://www.google.com/search"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


async def search_news(ticker: str, limit: int = 5) -> list[str]:
    """Return a list of recent news headline strings for the given ticker.

    Uses a simple web search approach.  Replace with a proper News API
    (e.g., Google News API, NewsData.io, or VNExpress RSS) for production.
    """
    query = f"{ticker} cổ phiếu chứng khoán Việt Nam tin tức"
    headlines: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                _SEARCH_URL,
                params={"q": query, "num": limit, "hl": "vi"},
                headers=_HEADERS,
            )
            resp.raise_for_status()

            # Very simple HTML title extraction – not a full parser
            text = resp.text
            headlines = _extract_titles(text, limit)

    except Exception as exc:
        logger.warning("News search failed for %s: %s", ticker, exc)

    if not headlines:
        headlines = [f"Không tìm thấy tin tức mới cho {ticker}."]

    return headlines


def search_news_sync(ticker: str, limit: int = 5) -> list[str]:
    """Synchronous wrapper for search_news."""
    query = f"{ticker} cổ phiếu chứng khoán Việt Nam tin tức"
    headlines: list[str] = []

    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(
                _SEARCH_URL,
                params={"q": query, "num": limit, "hl": "vi"},
                headers=_HEADERS,
            )
            resp.raise_for_status()
            headlines = _extract_titles(resp.text, limit)

    except Exception as exc:
        logger.warning("News search failed for %s: %s", ticker, exc)

    if not headlines:
        headlines = [f"Không tìm thấy tin tức mới cho {ticker}."]

    return headlines


def _extract_titles(html: str, limit: int) -> list[str]:
    """Extract up to `limit` text snippets from search results HTML.

    This is intentionally simple. For production, use a proper API or
    BeautifulSoup / lxml.
    """
    import re

    titles: list[str] = []
    # Pattern to extract <h3> content (Google search result titles)
    pattern = re.compile(r"<h3[^>]*>(.*?)</h3>", re.DOTALL)
    for match in pattern.finditer(html):
        text = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        if text and len(text) > 10:
            titles.append(text)
            if len(titles) >= limit:
                break
    return titles
