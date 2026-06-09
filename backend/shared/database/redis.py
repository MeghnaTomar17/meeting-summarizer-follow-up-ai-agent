"""
Purpose: Redis connection for caching, sessions, and Celery broker.
Future responsibilities: Connection pool, pub/sub, distributed locks.
Service ownership: Shared module (gateway-service, worker-service).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis


_redis: "Redis | None" = None


async def get_redis() -> "Redis":
    """Return async Redis client — TODO: wire settings.redis_url."""
    global _redis
    if _redis is None:
        raise NotImplementedError("Redis client not configured")
    return _redis


async def close_redis() -> None:
    """Close Redis connections on shutdown."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
