"""Search service configuration."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

from cryptography.hazmat.primitives.serialization import load_pem_public_key
from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator

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


class SearchSettings(SharedSettings):
    """Search service-specific settings (vector store + embeddings)."""

    service_name: str = "search-service"
    internal_principal_public_key: str = Field(
        default=_DEV_INTERNAL_PRINCIPAL_PUBLIC_KEY
    )
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr | None = None
    qdrant_timeout_seconds: int = Field(default=5, ge=1, le=120)
    qdrant_collection_name: str = Field(default="meeting_chunks", min_length=1)
    qdrant_distance_metric: Literal["Cosine", "Dot", "Euclid"] = "Cosine"
    embedding_provider: str = Field(default="openai", min_length=1)
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = Field(default=1536, ge=1)
    embedding_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "OPENAI_API_KEY", "embedding_api_key"
        ),
        repr=False,
    )
    embedding_base_url: str | None = None
    embedding_timeout_seconds: float = Field(default=30.0, gt=0)
    transcript_chunk_max_characters: int = Field(default=2000, ge=1)

    @field_validator("internal_principal_public_key")
    @classmethod
    def validate_internal_principal_public_key(cls, value: str) -> str:
        try:
            load_pem_public_key(value.encode())
        except (TypeError, ValueError) as error:
            raise ValueError(
                "INTERNAL_PRINCIPAL_PUBLIC_KEY must be a valid PEM public key"
            ) from error
        return value

    @model_validator(mode="after")
    def require_deployment_internal_key(self) -> SearchSettings:
        if (
            self.app_env == AppEnv.PRODUCTION
            and self.internal_principal_public_key == _DEV_INTERNAL_PRINCIPAL_PUBLIC_KEY
        ):
            raise ValueError(
                "INTERNAL_PRINCIPAL_PUBLIC_KEY must be configured in production"
            )
        return self

    @field_validator("qdrant_url")
    @classmethod
    def validate_qdrant_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("QDRANT_URL must be an HTTP or HTTPS URL with a host")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("QDRANT_URL must not contain embedded credentials")
        return value.rstrip("/")

    @field_validator("qdrant_collection_name")
    @classmethod
    def validate_collection_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or any(not (char.isalnum() or char in "_-") for char in normalized):
            raise ValueError("QDRANT_COLLECTION_NAME may contain only letters, digits, '_' and '-'")
        return normalized

    @field_validator("embedding_provider")
    @classmethod
    def validate_embedding_provider(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Embedding provider name must not be blank")
        return normalized.lower()

    @field_validator("embedding_model")
    @classmethod
    def validate_embedding_model(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Embedding model name must not be blank")
        return normalized

    @field_validator("embedding_base_url")
    @classmethod
    def validate_embedding_base_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip()
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("EMBEDDING_BASE_URL must be an HTTP or HTTPS URL with a host")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("EMBEDDING_BASE_URL must not contain embedded credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("EMBEDDING_BASE_URL must not contain query or fragment data")
        return normalized.rstrip("/")


get_settings = cached_settings_factory(SearchSettings)

__all__ = ["SearchSettings", "get_settings"]
