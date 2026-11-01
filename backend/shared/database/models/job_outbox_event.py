"""Committed processing-job events awaiting signed queue publication."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.database.base import Base
from shared.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class JobOutboxEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "job_outbox_events"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'published')", name="ck_job_outbox_events_status"),
        CheckConstraint("attempt_count >= 0", name="ck_job_outbox_events_attempt_count"),
        CheckConstraint(
            "ambiguity_recovery_count >= 0",
            name="ck_job_outbox_events_ambiguity_recovery_count",
        ),
        CheckConstraint(
            "(status = 'pending' AND published_at IS NULL) OR "
            "(status = 'published' AND published_at IS NOT NULL)",
            name="ck_job_outbox_events_publish_state",
        ),
        CheckConstraint(
            "(lock_token IS NULL AND locked_until IS NULL) OR "
            "(lock_token IS NOT NULL AND locked_until IS NOT NULL)",
            name="ck_job_outbox_events_lock_state",
        ),
        Index("uq_job_outbox_events_job_id", "job_id", unique=True),
        Index("ix_job_outbox_events_pending", "status", "created_at"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("processing_jobs.job_id", ondelete="CASCADE"), nullable=False
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    ambiguity_recovery_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    lock_token: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
