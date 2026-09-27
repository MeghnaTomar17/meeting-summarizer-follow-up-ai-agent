"""ORM model for decisions recorded from a meeting."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.database.base import Base
from shared.database.mixins import UUIDPrimaryKeyMixin


class Decision(UUIDPrimaryKeyMixin, Base):
    """A decision associated with a meeting."""

    __tablename__ = "decisions"
    __table_args__ = (Index("ix_decisions_meeting_id", "meeting_id"),)

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "meetings.id",
            name="fk_decisions_meeting_id_meetings",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    participants: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    meeting: Mapped["Meeting"] = relationship("Meeting", back_populates="decisions")
