"""
Purpose: ORM model for persisted meetings.
Service ownership: meeting-service.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import DateTime, Enum as SQLEnum, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.database.base import Base
from shared.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class MeetingStatus(str, Enum):
    """Persisted lifecycle states for a meeting."""

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class Meeting(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Meeting domain entity."""

    __tablename__ = "meetings"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    participants: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )

    status: Mapped[MeetingStatus] = mapped_column(
        SQLEnum(
            MeetingStatus,
            name="meeting_status",
            native_enum=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=MeetingStatus.PENDING,
        server_default=MeetingStatus.PENDING.value,
    )

    transcript: Mapped["Transcript | None"] = relationship(
        "Transcript",
        back_populates="meeting",
        uselist=False,
        cascade="all, delete-orphan",
    )
