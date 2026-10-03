"""
Purpose: Redis client for Celery broker/result backend and auxiliary queue operations.
Future responsibilities: Simple job enqueue, pub/sub job status.
Service ownership: worker-service.
"""

from __future__ import annotations

from app.config.settings import get_settings


def get_sync_redis_url() -> str:
    """Return Celery broker Redis URL from worker settings."""
    return str(get_settings().celery_broker_url)
