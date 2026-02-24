"""Centralized configuration loaded from environment variables."""

from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings – populated from .env file or environment."""

    # AI
    anthropic_api_key: str = Field(default="", description="Anthropic API key")
    anthropic_model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Claude model identifier",
    )

    # Supabase
    supabase_url: str = Field(default="", description="Supabase project URL")
    supabase_key: str = Field(default="", description="Supabase anon/service key")

    # Telegram
    telegram_bot_token: str = Field(default="", description="Telegram Bot token")
    telegram_chat_id: str = Field(default="", description="Telegram chat ID for alerts")

    # LangSmith
    langsmith_api_key: str = Field(default="", description="LangSmith API key")
    langsmith_tracing: str = Field(default="false", description="Enable LangSmith tracing")
    langchain_project: str = Field(default="vn-stock-copilot", description="LangSmith project name")

    # App
    app_env: str = Field(default="development")
    log_level: str = Field(default="INFO")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }


@lru_cache()
def get_settings() -> Settings:
    """Return a cached Settings singleton."""
    return Settings()
