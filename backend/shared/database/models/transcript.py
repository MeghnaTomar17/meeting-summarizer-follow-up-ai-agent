"""
Purpose: ORM model for persisted meeting transcripts.
Service ownership: meeting-service.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.database.base import Base
from shared.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Transcript(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable transcript revision with stable identity for processing jobs."""

    __table_args__ = (
        UniqueConstraint(
            "meeting_id", "revision_number", name="uq_transcripts_meeting_revision"
        ),
    )

    __tablename__ = "transcripts"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    revision_number: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")

    segments: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )

    language: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    meeting: Mapped["Meeting"] = relationship(
        "Meeting",
        back_populates="transcripts",
    )
