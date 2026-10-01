"""AI service configuration."""

from __future__ import annotations

from pydantic import Field, SecretStr

from shared.config.base import SharedSettings, cached_settings_factory


class AISettings(SharedSettings):
    """AI service settings.

    OpenAI is the first configured provider adapter. Gemini settings remain
    reserved for a future alternate provider and are not used by this block.
    """

    service_name: str = "ai-service"
    openai_api_key: SecretStr | None = Field(
        default=None, description="OpenAI API credential; required when the provider is called."
    )
    openai_model: str | None = Field(
        default=None, description="OpenAI model name; required when the provider is called."
    )
    openai_timeout_seconds: float = Field(
        default=30.0, gt=0, description="Maximum duration for an OpenAI request."
    )
    gemini_api_key: SecretStr | None = Field(
        default=None, description="Reserved for a future alternate provider; unused here."
    )
    gemini_model: str | None = Field(
        default=None, description="Reserved for a future alternate provider; unused here."
    )


get_settings = cached_settings_factory(AISettings)

__all__ = ["AISettings", "get_settings"]
