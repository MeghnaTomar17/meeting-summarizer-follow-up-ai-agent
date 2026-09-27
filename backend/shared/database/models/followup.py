"""ORM model for persisted, reviewable follow-up email drafts."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SQLEnum, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.database.base import Base
from shared.database.mixins import UUIDPrimaryKeyMixin


class FollowupStatus(str, Enum):
    """Persisted delivery states from the shared API contract."""

    DRAFT = "draft"
    SCHEDULED = "scheduled"
    SENT = "sent"
    FAILED = "failed"


class Followup(UUIDPrimaryKeyMixin, Base):
    """A generated follow-up email associated with a meeting."""

    __tablename__ = "followups"
    __table_args__ = (Index("ix_followups_meeting_id", "meeting_id"),)

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "meetings.id",
            name="fk_followups_meeting_id_meetings",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    recipients: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    status: Mapped[FollowupStatus] = mapped_column(
        SQLEnum(
            FollowupStatus,
            name="followup_status",
            native_enum=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=FollowupStatus.DRAFT,
        server_default=FollowupStatus.DRAFT.value,
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    meeting: Mapped["Meeting"] = relationship("Meeting", back_populates="followups")
