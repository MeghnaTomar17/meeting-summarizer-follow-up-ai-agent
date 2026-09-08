"""Database lifecycle helpers for gateway authentication persistence."""

from __future__ import annotations

from shared.config.base import SharedSettings
from shared.database import close_database, init_database


async def startup_database(settings: SharedSettings) -> None:
    """Initialize the shared PostgreSQL engine and session factory."""
    await init_database(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout,
        pool_recycle=settings.database_pool_recycle,
        echo=settings.database_echo,
    )


async def shutdown_database() -> None:
    """Dispose gateway database resources during application shutdown."""
    await close_database()
