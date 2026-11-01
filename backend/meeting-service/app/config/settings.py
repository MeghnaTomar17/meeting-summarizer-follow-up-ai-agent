"""Meeting service configuration."""

from __future__ import annotations

from urllib.parse import urlparse

from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from pydantic import Field, SecretStr, field_validator, model_validator

from shared.config.base import AppEnv, SharedSettings, cached_settings_factory
from shared.jobs.outbox_policy import (
    MAX_OUTBOX_AMBIGUITY_RECOVERY_CLAIMS,
    MAX_OUTBOX_PUBLICATION_ATTEMPTS,
    MAX_OUTBOX_RETRY_BASE_SECONDS,
    MAX_OUTBOX_RETRY_CAP_SECONDS,
)

_DEV_INTERNAL_PRINCIPAL_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAukQRnwX8isBsAONNUGF2
/uvWz4PaAfma2PaX8vQDRJhXrQwDHJjs9vYdV+0nOmS5TDLpA0p1VMxiIcUrDloZ
A1bB6Hk4Vc0IzTXclMOomE02pmGrX0hVE01QJopGXYxitk5k7q0cMerCKd0LDkP6
O6WT88rVs+SSVXSdCIaN/aj5EiD0sgpvHfA8AgZsK/zlSkcFDsyjIczS+w634fEn
84BG3KvPSnyZZA9Uwf4kk469P/kbvrt6beY0vyduPCJCWkSvtBd3R/M2omVYvtN4
QIgLpf6C+n5BY00o1o7j0UHpB2Eenj0eEaVjwqHCcqdtNxxBX0lPK80/3tNtWiQz
CQIDAQAB
-----END PUBLIC KEY-----"""


class MeetingSettings(SharedSettings):
    """Meeting service settings."""

    service_name: str = "meeting-service"
    ai_service_url: str = "http://localhost:8002"
    ai_service_timeout_seconds: float = Field(default=45.0, gt=0, le=120)
    outbox_publication_max_attempts: int = Field(
        default=MAX_OUTBOX_PUBLICATION_ATTEMPTS,
        ge=1,
        le=MAX_OUTBOX_PUBLICATION_ATTEMPTS,
    )
    outbox_publication_max_ambiguity_recovery_claims: int = Field(
        default=MAX_OUTBOX_AMBIGUITY_RECOVERY_CLAIMS,
        ge=0,
        le=MAX_OUTBOX_AMBIGUITY_RECOVERY_CLAIMS,
    )
    outbox_publication_retry_base_seconds: float = Field(
        default=MAX_OUTBOX_RETRY_BASE_SECONDS,
        gt=0,
        le=MAX_OUTBOX_RETRY_BASE_SECONDS,
    )
    outbox_publication_retry_max_seconds: float = Field(
        default=MAX_OUTBOX_RETRY_CAP_SECONDS,
        gt=0,
        le=MAX_OUTBOX_RETRY_CAP_SECONDS,
    )
    internal_principal_public_key: str = Field(
        default=_DEV_INTERNAL_PRINCIPAL_PUBLIC_KEY
    )
    outbox_publication_auth_private_key: SecretStr | None = None

    @field_validator("outbox_publication_auth_private_key", mode="before")
    @classmethod
    def empty_outbox_auth_key_is_unset(cls, value: object) -> object:
        return None if value == "" else value

    @model_validator(mode="after")
    def validate_outbox_retry_window(self) -> MeetingSettings:
        if self.outbox_publication_retry_max_seconds < self.outbox_publication_retry_base_seconds:
            raise ValueError(
                "OUTBOX_PUBLICATION_RETRY_MAX_SECONDS must be at least the retry base."
            )
        return self

    @model_validator(mode="after")
    def validate_production_internal_principal_public_key(self) -> MeetingSettings:
        public_key = self.internal_principal_public_key
        if self.app_env == AppEnv.PRODUCTION and public_key == _DEV_INTERNAL_PRINCIPAL_PUBLIC_KEY:
            msg = "INTERNAL_PRINCIPAL_PUBLIC_KEY must not use the development key in production"
            raise ValueError(msg)
        if self.app_env == AppEnv.PRODUCTION:
            try:
                load_pem_public_key(public_key.encode())
            except (TypeError, ValueError) as error:
                msg = "INTERNAL_PRINCIPAL_PUBLIC_KEY must be a valid PEM public key"
                raise ValueError(msg) from error
        parsed_url = urlparse(self.ai_service_url)
        if (
            parsed_url.scheme not in {"http", "https"}
            or not parsed_url.netloc
            or parsed_url.username
            or parsed_url.password
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise ValueError("AI_SERVICE_URL must be an absolute HTTP(S) URL without credentials.")
        auth_key = self.outbox_publication_auth_private_key
        if self.app_env == AppEnv.PRODUCTION and auth_key is None:
            raise ValueError("OUTBOX_PUBLICATION_AUTH_PRIVATE_KEY is required in production")
        if auth_key is not None:
            try:
                parsed_key = load_pem_private_key(
                    auth_key.get_secret_value().replace("\\n", "\n").encode(),
                    password=None,
                )
            except (TypeError, ValueError) as error:
                raise ValueError("OUTBOX_PUBLICATION_AUTH_PRIVATE_KEY must be valid PEM") from error
            if not isinstance(parsed_key, RSAPrivateKey) or parsed_key.key_size < 2048:
                raise ValueError("OUTBOX_PUBLICATION_AUTH_PRIVATE_KEY must be RSA-2048 or stronger")
        return self


Settings = MeetingSettings

get_settings = cached_settings_factory(MeetingSettings)

__all__ = ["MeetingSettings", "Settings", "get_settings"]
