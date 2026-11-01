"""Owner-scoped idempotency records for atomic meeting submission."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.database.base import Base
from shared.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class MeetingSubmissionIdempotency(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "meeting_submission_idempotency"
    __table_args__ = (
        Index(
            "uq_meeting_submission_idempotency_owner_operation_key",
            "owner_id",
            "operation",
            "idempotency_key",
            unique=True,
        ),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    transcript_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("processing_jobs.job_id", ondelete="CASCADE"), nullable=False
    )
