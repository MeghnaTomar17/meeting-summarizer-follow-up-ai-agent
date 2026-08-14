"""Gateway service configuration."""

from __future__ import annotations

from pydantic import Field, SecretStr, model_validator

from shared.config.base import AppEnv, SharedSettings, cached_settings_factory

_DEV_JWT_SECRET = "dev-only-jwt-secret-not-for-production-use"

_INSECURE_JWT_SECRETS = frozenset(
    {
        "change-me",
        "change-me-use-a-long-random-string",
        _DEV_JWT_SECRET,
    }
)


class GatewaySettings(SharedSettings):
    """Gateway-specific settings (auth + downstream service URLs)."""

    service_name: str = "gateway-service"
    jwt_secret: SecretStr = Field(default=SecretStr(_DEV_JWT_SECRET))
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    meeting_service_url: str = "http://localhost:8001"
    ai_service_url: str = "http://localhost:8002"
    search_service_url: str = "http://localhost:8003"

    @model_validator(mode="after")
    def validate_production_jwt_secret(self) -> GatewaySettings:
        if self.app_env != AppEnv.PRODUCTION:
            return self

        secret = self.jwt_secret.get_secret_value()
        if secret in _INSECURE_JWT_SECRETS or len(secret) < 32:
            msg = "JWT_SECRET must be a strong secret (min 32 characters) in production"
            raise ValueError(msg)
        return self


get_settings = cached_settings_factory(GatewaySettings)

__all__ = ["GatewaySettings", "get_settings"]
