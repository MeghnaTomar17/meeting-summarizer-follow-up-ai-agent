"""ORM model for one qualitative insight associated with a meeting."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum as SQLEnum, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.database.base import Base
from shared.database.mixins import UUIDPrimaryKeyMixin
from shared.schemas.meeting_insight import InsightCategory


class MeetingInsight(UUIDPrimaryKeyMixin, Base):
    """Immutable generated insight snapshot; regeneration may add another row."""

    __tablename__ = "meeting_insights"
    __table_args__ = (Index("ix_meeting_insights_meeting_id", "meeting_id"),)

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "meetings.id",
            name="fk_meeting_insights_meeting_id_meetings",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    category: Mapped[InsightCategory] = mapped_column(
        SQLEnum(
            InsightCategory,
            name="meeting_insight_category",
            native_enum=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    meeting: Mapped["Meeting"] = relationship("Meeting", back_populates="insights")


__all__ = ["MeetingInsight"]
