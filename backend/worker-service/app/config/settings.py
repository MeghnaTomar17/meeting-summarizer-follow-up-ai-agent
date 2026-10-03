"""Worker service configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, RedisDsn, field_validator

from shared.config.base import SharedSettings, cached_settings_factory


class WorkerSettings(SharedSettings):
    """Worker service-specific settings (Celery)."""

    service_name: str = "worker-service"
    celery_broker_url: RedisDsn = "redis://localhost:6379/1"
    celery_task_serializer: Literal["json"] = "json"
    celery_result_serializer: Literal["json"] = "json"
    celery_accept_content: tuple[Literal["json"], ...] = ("json",)
    celery_timezone: Literal["UTC"] = "UTC"
    celery_task_acks_late: bool = False
    celery_task_reject_on_worker_lost: bool = False
    celery_worker_prefetch_multiplier: int = Field(default=1, ge=1)
    celery_worker_concurrency: int = Field(default=1, ge=1)

    @field_validator("celery_broker_url", mode="before")
    @classmethod
    def validate_redis_broker(cls, value: object) -> object:
        if not isinstance(value, str) or not value.startswith(("redis://", "rediss://")):
            raise ValueError("CELERY_BROKER_URL must use the Redis transport.")
        return value


get_settings = cached_settings_factory(WorkerSettings)

__all__ = ["WorkerSettings", "get_settings"]
