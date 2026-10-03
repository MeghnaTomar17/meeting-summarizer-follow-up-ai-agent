"""Worker service configuration."""

from __future__ import annotations

from typing import Literal

from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from pydantic import Field, RedisDsn, SecretStr, field_validator, model_validator

from shared.config.base import AppEnv, SharedSettings, cached_settings_factory


class WorkerSettings(SharedSettings):
    """Worker service-specific settings (Celery)."""

    service_name: str = "worker-service"
    background_job_verification_public_key: SecretStr | None = None
    background_job_issuer: str = "ai-service"
    background_job_audience: str = "mannerai-worker"
    background_job_authorization_max_age_seconds: int = Field(default=120, ge=1, le=300)
    celery_broker_url: RedisDsn = "redis://localhost:6379/1"
    celery_broker_connection_timeout: float = Field(default=5.0, gt=0, le=60)
    celery_broker_socket_connect_timeout: float = Field(default=5.0, gt=0, le=60)
    celery_broker_socket_timeout: float = Field(default=10.0, gt=0, le=120)
    celery_task_serializer: Literal["json"] = "json"
    celery_result_serializer: Literal["json"] = "json"
    celery_accept_content: tuple[Literal["json"], ...] = ("json",)
    celery_timezone: Literal["UTC"] = "UTC"
    celery_task_acks_late: bool = False
    celery_task_reject_on_worker_lost: bool = False
    celery_worker_prefetch_multiplier: int = Field(default=1, ge=1)
    celery_worker_concurrency: int = Field(default=1, ge=1)

    @field_validator("background_job_verification_public_key", mode="before")
    @classmethod
    def empty_job_key_is_unset(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("celery_broker_url", mode="before")
    @classmethod
    def validate_redis_broker(cls, value: object) -> object:
        if not isinstance(value, str) or not value.startswith(("redis://", "rediss://")):
            raise ValueError("CELERY_BROKER_URL must use the Redis transport.")
        return value

    @model_validator(mode="after")
    def validate_job_verification_key(self) -> WorkerSettings:
        value = self.background_job_verification_public_key
        if self.app_env == AppEnv.PRODUCTION and value is None:
            raise ValueError("BACKGROUND_JOB_VERIFICATION_PUBLIC_KEY is required in production")
        if value is not None:
            try:
                key = load_pem_public_key(
                    value.get_secret_value().replace("\\n", "\n").encode()
                )
            except (TypeError, ValueError) as error:
                raise ValueError("BACKGROUND_JOB_VERIFICATION_PUBLIC_KEY must be valid PEM") from error
            if not isinstance(key, RSAPublicKey) or key.key_size < 2048:
                raise ValueError("BACKGROUND_JOB_VERIFICATION_PUBLIC_KEY must be RSA-2048 or stronger")
        return self


get_settings = cached_settings_factory(WorkerSettings)

__all__ = ["WorkerSettings", "get_settings"]
