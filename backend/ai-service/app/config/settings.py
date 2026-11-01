"""AI service configuration."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from pydantic import Field, RedisDsn, SecretStr, field_validator, model_validator

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

    Application composition is Ollama-only. Legacy OpenAI adapter settings are
    retained for its isolated adapter tests but are not used by runtime wiring.
    Gemini settings remain reserved and have no runtime provider.
    """

    service_name: str = "ai-service"
    internal_principal_public_key: str = _DEV_INTERNAL_PRINCIPAL_PUBLIC_KEY
    background_job_signing_private_key: SecretStr | None = None
    background_job_issuer: str = "ai-service"
    background_job_audience: str = "mannerai-worker"
    background_job_authorization_expire_seconds: int = Field(default=120, ge=1, le=300)
    outbox_publication_auth_public_key: SecretStr | None = None
    celery_broker_url: RedisDsn = "redis://localhost:6379/1"
    celery_broker_connection_timeout: float = Field(default=5.0, gt=0, le=60)
    celery_broker_socket_connect_timeout: float = Field(default=5.0, gt=0, le=60)
    celery_broker_socket_timeout: float = Field(default=10.0, gt=0, le=120)
    ai_model_provider: Literal["ollama"] = "ollama"
    ai_model: str = "llama3.2:3b"
    ollama_base_url: str = "http://localhost:11434"
    ollama_timeout_seconds: float = Field(default=30.0, gt=0)
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

    @field_validator("ollama_base_url")
    @classmethod
    def validate_ollama_base_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("OLLAMA_BASE_URL must be an absolute HTTP(S) URL.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("OLLAMA_BASE_URL must not contain credentials or query data.")
        return value.rstrip("/")

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

    @field_validator("outbox_publication_auth_public_key", mode="before")
    @classmethod
    def empty_outbox_publication_key_is_unset(cls, value: object) -> object:
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
        publication_key = self.outbox_publication_auth_public_key
        if self.app_env == AppEnv.PRODUCTION and publication_key is None:
            raise ValueError("OUTBOX_PUBLICATION_AUTH_PUBLIC_KEY is required in production")
        if publication_key is not None:
            try:
                key = load_pem_public_key(
                    publication_key.get_secret_value().replace("\\n", "\n").encode()
                )
            except (TypeError, ValueError) as error:
                raise ValueError("OUTBOX_PUBLICATION_AUTH_PUBLIC_KEY must be valid PEM") from error
            if not isinstance(key, RSAPublicKey) or key.key_size < 2048:
                raise ValueError("OUTBOX_PUBLICATION_AUTH_PUBLIC_KEY must be RSA-2048 or stronger")
            publication_bytes = key.public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            gateway_key = load_pem_public_key(self.internal_principal_public_key.encode())
            if publication_bytes == gateway_key.public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            ):
                raise ValueError("OUTBOX_PUBLICATION_AUTH_PUBLIC_KEY must be distinct from Gateway keys")
            if value is not None:
                job_signing_key = load_pem_private_key(
                    value.get_secret_value().replace("\\n", "\n").encode(), password=None
                )
                if publication_bytes == job_signing_key.public_key().public_bytes(
                    serialization.Encoding.DER,
                    serialization.PublicFormat.SubjectPublicKeyInfo,
                ):
                    raise ValueError(
                        "OUTBOX_PUBLICATION_AUTH_PUBLIC_KEY must be distinct from job-signing keys"
                    )
        return self

    @field_validator("celery_broker_url", mode="before")
    @classmethod
    def validate_redis_broker(cls, value: object) -> object:
        if not isinstance(value, str) or not value.startswith(("redis://", "rediss://")):
            raise ValueError("CELERY_BROKER_URL must use the Redis transport.")
        return value


get_settings = cached_settings_factory(AISettings)

__all__ = ["AISettings", "get_settings"]
