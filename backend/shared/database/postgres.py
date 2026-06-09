"""
Purpose: Async PostgreSQL engine and session factory (SQLAlchemy 2.0 + asyncpg).
Future responsibilities: Connection pooling, session lifecycle, health checks.
Service ownership: Shared module (all backend services with relational data).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


_engine: "AsyncEngine | None" = None
_session_factory: "async_sessionmaker[AsyncSession] | None" = None


async def init_postgres(database_url: str) -> None:
    """Initialize async engine and session factory — call from app lifespan."""
    global _engine, _session_factory
    if _engine is not None:
        return

    # TODO: from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    # _engine = create_async_engine(database_url, pool_pre_ping=True, pool_size=10)
    # _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    _ = database_url
    raise NotImplementedError("PostgreSQL engine not configured")


async def get_session() -> AsyncGenerator["AsyncSession", None]:
    """FastAPI dependency — yields an async DB session per request."""
    if _session_factory is None:
        raise NotImplementedError("PostgreSQL session factory not initialized")
    async with _session_factory() as session:
        yield session


async def close_postgres() -> None:
    """Dispose engine on application shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
