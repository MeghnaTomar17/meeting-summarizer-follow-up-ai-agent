"""AI service configuration."""

from __future__ import annotations

from pydantic import Field, SecretStr

from shared.config.base import SharedSettings, cached_settings_factory


class AISettings(SharedSettings):
    """AI service settings.

    Provider fields are retained as optional legacy configuration for later
    roadmap blocks. The Phase 6 foundation does not read or require them.
    """

    service_name: str = "ai-service"
    openai_api_key: SecretStr | None = Field(
        default=None, description="Reserved for a later provider block; unused here."
    )
    openai_model: str | None = Field(
        default=None, description="Reserved for a later provider block; unused here."
    )
    gemini_api_key: SecretStr | None = Field(
        default=None, description="Reserved for a later provider block; unused here."
    )
    gemini_model: str | None = Field(
        default=None, description="Reserved for a later provider block; unused here."
    )


get_settings = cached_settings_factory(AISettings)

__all__ = ["AISettings", "get_settings"]
