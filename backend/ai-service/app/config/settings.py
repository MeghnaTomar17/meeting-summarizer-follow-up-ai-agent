"""AI service configuration."""

from __future__ import annotations

from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from pydantic import Field, SecretStr, field_validator, model_validator

from shared.config.base import AppEnv, SharedSettings, cached_settings_factory


class AISettings(SharedSettings):
    """AI service settings.

    OpenAI is the first configured provider adapter. Gemini settings remain
    reserved for a future alternate provider and are not used by this block.
    """

    service_name: str = "ai-service"
    background_job_signing_private_key: SecretStr | None = None
    background_job_issuer: str = "ai-service"
    background_job_audience: str = "mannerai-worker"
    background_job_authorization_expire_seconds: int = Field(default=120, ge=1, le=300)
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

    @field_validator("background_job_signing_private_key", mode="before")
    @classmethod
    def empty_job_key_is_unset(cls, value: object) -> object:
        return None if value == "" else value

    @model_validator(mode="after")
    def validate_job_signing_key(self) -> AISettings:
        value = self.background_job_signing_private_key
        if self.app_env == AppEnv.PRODUCTION and value is None:
            raise ValueError("BACKGROUND_JOB_SIGNING_PRIVATE_KEY is required in production")
        if value is not None:
            try:
                key = load_pem_private_key(
                    value.get_secret_value().replace("\\n", "\n").encode(), password=None
                )
            except (TypeError, ValueError) as error:
                raise ValueError("BACKGROUND_JOB_SIGNING_PRIVATE_KEY must be valid PEM") from error
            if not isinstance(key, RSAPrivateKey) or key.key_size < 2048:
                raise ValueError("BACKGROUND_JOB_SIGNING_PRIVATE_KEY must be RSA-2048 or stronger")
        return self


get_settings = cached_settings_factory(AISettings)

__all__ = ["AISettings", "get_settings"]
