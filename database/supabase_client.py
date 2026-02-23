"""Supabase client singleton."""

from __future__ import annotations

import logging

from supabase import create_client, Client

from config import get_settings

logger = logging.getLogger(__name__)

_client: Client | None = None


def get_supabase() -> Client:
    """Return a cached Supabase client instance."""
    global _client
    if _client is None:
        settings = get_settings()
        if not settings.supabase_url or not settings.supabase_key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_KEY must be set in environment."
            )
        _client = create_client(settings.supabase_url, settings.supabase_key)
        logger.info("Supabase client initialised → %s", settings.supabase_url)
    return _client
