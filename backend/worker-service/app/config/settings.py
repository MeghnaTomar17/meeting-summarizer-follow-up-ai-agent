"""Worker service configuration."""

from __future__ import annotations

from shared.config.base import SharedSettings, cached_settings_factory


class WorkerSettings(SharedSettings):
    """Worker service-specific settings (Celery)."""

    service_name: str = "worker-service"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"


get_settings = cached_settings_factory(WorkerSettings)

__all__ = ["WorkerSettings", "get_settings"]
