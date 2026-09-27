"""ORM model for versioned, persisted meeting summaries."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.database.base import Base
from shared.database.mixins import UUIDPrimaryKeyMixin


class Summary(UUIDPrimaryKeyMixin, Base):
    """One generated summary version belonging to a meeting."""

    __tablename__ = "summaries"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_summaries_version_positive"),
        UniqueConstraint(
            "meeting_id", "version", name="uq_summaries_meeting_version"
        ),
        Index(
            "ix_summaries_meeting_version_desc",
            "meeting_id",
            text("version DESC"),
        ),
    )

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "meetings.id",
            name="fk_summaries_meeting_id_meetings",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    key_topics: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    model_provider: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    meeting: Mapped["Meeting"] = relationship("Meeting", back_populates="summaries")
