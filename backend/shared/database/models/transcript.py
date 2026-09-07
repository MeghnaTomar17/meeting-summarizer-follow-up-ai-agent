"""
Purpose: ORM model for persisted meeting transcripts.
Service ownership: meeting-service.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.database.base import Base
from shared.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Transcript(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Transcript metadata and structured segments for a meeting."""

    __tablename__ = "transcripts"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

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
        back_populates="transcript",
    )