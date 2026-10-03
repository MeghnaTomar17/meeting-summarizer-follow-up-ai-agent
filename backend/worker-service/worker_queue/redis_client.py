"""
Purpose: Redis URL access for the Celery broker.
Connection lifecycle: Celery opens broker connections only when publishing or starting a worker.
Service ownership: worker-service.
"""

from __future__ import annotations

from app.config.settings import get_settings


def get_sync_redis_url() -> str:
    """Return the configured broker URL without opening a Redis connection."""
    return str(get_settings().celery_broker_url)
