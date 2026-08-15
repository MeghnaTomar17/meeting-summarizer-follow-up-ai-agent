"""
Purpose: SQLAlchemy declarative base for ORM models.
Future responsibilities: Shared metadata, Alembic autogenerate target.
Service ownership: Shared module.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Canonical SQLAlchemy ORM base for all persistent models."""
