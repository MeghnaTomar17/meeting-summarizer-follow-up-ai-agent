"""AI service configuration."""

from __future__ import annotations

from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from pydantic import Field, SecretStr, field_validator, model_validator

from shared.config.base import AppEnv, SharedSettings, cached_settings_factory

_DEV_INTERNAL_PRINCIPAL_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAukQRnwX8isBsAONNUGF2
/uvWz4PaAfma2PaX8vQDRJhXrQwDHJjs9vYdV+0nOmS5TDLpA0p1VMxiIcUrDloZ
A1bB6Hk4Vc0IzTXclMOomE02pmGrX0hVE01QJopGXYxitk5k7q0cMerCKd0LDkP6
O6WT88rVs+SSVXSdCIaN/aj5EiD0sgpvHfA8AgZsK/zlSkcFDsyjIczS+w634fEn
84BG3KvPSnyZZA9Uwf4kk469P/kbvrt6beY0vyduPCJCWkSvtBd3R/M2omVYvtN4
QIgLpf6C+n5BY00o1o7j0UHpB2Eenj0eEaVjwqHCcqdtNxxBX0lPK80/3tNtWiQz
CQIDAQAB
-----END PUBLIC KEY-----"""


class AISettings(SharedSettings):
    """AI service settings.

    OpenAI is the first configured provider adapter. Gemini settings remain
    reserved for a future alternate provider and are not used by this block.
    """

    service_name: str = "ai-service"
    internal_principal_public_key: str = _DEV_INTERNAL_PRINCIPAL_PUBLIC_KEY
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

    @model_validator(mode="after")
    def validate_internal_principal_key(self) -> AISettings:
        if self.app_env == AppEnv.PRODUCTION and self.internal_principal_public_key == _DEV_INTERNAL_PRINCIPAL_PUBLIC_KEY:
            raise ValueError("INTERNAL_PRINCIPAL_PUBLIC_KEY must be configured in production")
        try:
            load_pem_public_key(self.internal_principal_public_key.encode())
        except (TypeError, ValueError) as error:
            raise ValueError("INTERNAL_PRINCIPAL_PUBLIC_KEY must be a valid PEM public key") from error
        return self

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
