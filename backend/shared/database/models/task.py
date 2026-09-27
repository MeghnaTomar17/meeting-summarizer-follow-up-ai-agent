"""ORM model for meeting action items."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SQLEnum, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.database.base import Base
from shared.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class TaskStatus(str, Enum):
    """Persisted task lifecycle states from the shared API contract."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class Task(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An action item extracted from or associated with a meeting."""

    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_meeting_status", "meeting_id", "status"),
        Index("ix_tasks_assignee_status", "assignee_id", "status"),
    )

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "meetings.id",
            name="fk_tasks_meeting_id_meetings",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            name="fk_tasks_assignee_id_users",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[TaskStatus] = mapped_column(
        SQLEnum(
            TaskStatus,
            name="task_status",
            native_enum=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=TaskStatus.OPEN,
        server_default=TaskStatus.OPEN.value,
    )

    meeting: Mapped["Meeting"] = relationship("Meeting", back_populates="tasks")
    assignee: Mapped["User | None"] = relationship(
        "User", back_populates="assigned_tasks"
    )
