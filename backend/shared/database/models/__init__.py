"""
SQLAlchemy ORM models — map to PostgreSQL tables.

Import all model modules here so Alembic metadata discovery
remains complete.
"""

from shared.database.base import Base
from shared.database.models.decision import Decision
from shared.database.models.followup import Followup, FollowupStatus
from shared.database.models.meeting import Meeting, MeetingStatus
from shared.database.models.meeting_insight import MeetingInsight
from shared.database.models.processing_job import ProcessingJobRecord
from shared.database.models.refresh_session import RefreshSession
from shared.database.models.summary import Summary
from shared.database.models.task import Task, TaskStatus
from shared.database.models.transcript import Transcript
from shared.database.models.user import User

__all__ = [
    "Base",
    "Decision",
    "Followup",
    "FollowupStatus",
    "Meeting",
    "MeetingInsight",
    "MeetingStatus",
    "ProcessingJobRecord",
    "RefreshSession",
    "Summary",
    "Task",
    "TaskStatus",
    "Transcript",
    "User",
]
