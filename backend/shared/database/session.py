"""
Purpose: Async SQLAlchemy session factory and FastAPI dependency.
Service ownership: Shared module.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from shared.database.engine import create_database_engine, dispose_database_engine

logger = logging.getLogger("shared.database.session")

_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_session_factory() -> async_sessionmaker[AsyncSession] | None:
    """Return the configured session factory when initialized."""
    return _session_factory


def configure_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Bind the canonical async session factory to an engine."""
    global _session_factory
    _session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    logger.info(
        "database_session_factory_configured",
        extra={"event": "database_session_factory_configured"},
    )
    return _session_factory


async def init_database(
    database_url: str,
    *,
    pool_size: int,
    max_overflow: int,
    pool_timeout: int,
    pool_recycle: int,
    echo: bool,
) -> None:
    """Initialize engine and session factory — call from application lifespan."""
    engine = create_database_engine(
        database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=pool_recycle,
        echo=echo,
    )
    configure_session_factory(engine)


async def close_database() -> None:
    """Dispose engine and reset session factory on application shutdown."""
    global _session_factory
    await dispose_database_engine()
    _session_factory = None
    logger.info(
        "database_session_factory_reset",
        extra={"event": "database_session_factory_reset"},
    )


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a request-scoped async database session."""
    if _session_factory is None:
        msg = "Database session factory not initialized"
        raise RuntimeError(msg)

    async with _session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
