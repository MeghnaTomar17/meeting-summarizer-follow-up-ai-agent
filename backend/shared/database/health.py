"""
Purpose: PostgreSQL connectivity helpers for readiness checks.
Service ownership: Shared module.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from shared.database.engine import get_engine

logger = logging.getLogger("shared.database.health")


async def check_postgres_connectivity(engine: AsyncEngine | None = None) -> bool:
    """Return True when PostgreSQL responds to a minimal SELECT 1 probe."""
    active_engine = engine or get_engine()
    if active_engine is None:
        return False

    try:
        async with active_engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except (SQLAlchemyError, OSError):
        logger.warning(
            "postgres_connectivity_check_failed",
            extra={"event": "postgres_connectivity_check_failed"},
        )
        return False
