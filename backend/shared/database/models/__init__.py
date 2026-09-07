"""
SQLAlchemy ORM models — map to PostgreSQL tables.

Import all model modules here so Alembic metadata discovery
remains complete.
"""

from shared.database.base import Base
from shared.database.models.meeting import Meeting, MeetingStatus
from shared.database.models.transcript import Transcript

__all__ = [
    "Base",
    "Meeting",
    "MeetingStatus",
    "Transcript",
]