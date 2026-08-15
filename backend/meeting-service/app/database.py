"""
Purpose: Database lifecycle helpers for meeting-service.
Service ownership: meeting-service.
"""

from __future__ import annotations

from shared.database import close_database, init_database
from shared.config.base import SharedSettings


async def startup_database(settings: SharedSettings) -> None:
    """Initialize PostgreSQL engine and session factory."""
    await init_database(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout,
        pool_recycle=settings.database_pool_recycle,
        echo=settings.database_echo,
    )


async def shutdown_database() -> None:
    """Dispose PostgreSQL resources on service shutdown."""
    await close_database()
