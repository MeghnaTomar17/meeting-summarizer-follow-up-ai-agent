"""AI service configuration."""

from __future__ import annotations

from pydantic import SecretStr

from shared.config.base import SharedSettings, cached_settings_factory


class AISettings(SharedSettings):
    """AI service-specific settings (LLM providers)."""

    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-1.5-flash"


get_settings = cached_settings_factory(AISettings)

__all__ = ["AISettings", "get_settings"]
