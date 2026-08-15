"""
Purpose: Async PostgreSQL engine lifecycle management.
Service ownership: Shared module.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

logger = logging.getLogger("shared.database.engine")

_engine: AsyncEngine | None = None


def get_engine() -> AsyncEngine | None:
    """Return the process-wide async engine when initialized."""
    return _engine


def create_database_engine(
    database_url: str,
    *,
    pool_size: int,
    max_overflow: int,
    pool_timeout: int,
    pool_recycle: int,
    echo: bool,
) -> AsyncEngine:
    """Create and cache the async SQLAlchemy engine for the current process."""
    global _engine
    if _engine is not None:
        return _engine

    _engine = create_async_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=pool_recycle,
        echo=echo,
    )
    logger.info(
        "database_engine_initialized",
        extra={
            "event": "database_engine_initialized",
            "pool_size": pool_size,
            "max_overflow": max_overflow,
        },
    )
    return _engine


async def dispose_database_engine() -> None:
    """Dispose the async engine and release pooled connections."""
    global _engine
    if _engine is None:
        return

    await _engine.dispose()
    _engine = None
    logger.info(
        "database_engine_disposed",
        extra={"event": "database_engine_disposed"},
    )
