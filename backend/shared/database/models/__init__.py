"""
SQLAlchemy ORM models — map to PostgreSQL tables (see database/postgresql/tables.md).

Import future model modules here so Alembic metadata discovery remains complete.
"""

from shared.database.base import Base

__all__ = ["Base"]
