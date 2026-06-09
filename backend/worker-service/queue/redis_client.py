"""
Purpose: Redis client for RQ or auxiliary queue operations.
Future responsibilities: Simple job enqueue, pub/sub job status.
Service ownership: worker-service.
"""

from __future__ import annotations

# TODO: Optional RQ queue alongside Celery for lightweight tasks


def get_sync_redis_url() -> str:
    """Return Redis URL for RQ — TODO: from settings."""
    return "redis://localhost:6379/0"
