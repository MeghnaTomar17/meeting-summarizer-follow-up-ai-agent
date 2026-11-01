"""Add owner idempotency and processing outbox records.

Revision ID: 0009_atomic_meeting_submission
Revises: 0008_transcript_revisions
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0009_atomic_meeting_submission"
down_revision: Union[str, None] = "0008_transcript_revisions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "meeting_submission_idempotency",
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transcript_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["transcript_id"], ["transcripts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["processing_jobs.job_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_meeting_submission_idempotency_owner_operation_key",
        "meeting_submission_idempotency",
        ["owner_id", "operation", "idempotency_key"],
        unique=True,
    )

    op.create_table(
        "job_outbox_events",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("lock_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_category", sa.String(length=64), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'published')", name="ck_job_outbox_events_status"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_job_outbox_events_attempt_count"),
        sa.CheckConstraint(
            "(status = 'pending' AND published_at IS NULL) OR "
            "(status = 'published' AND published_at IS NOT NULL)",
            name="ck_job_outbox_events_publish_state",
        ),
        sa.CheckConstraint(
            "(lock_token IS NULL AND locked_until IS NULL) OR "
            "(lock_token IS NOT NULL AND locked_until IS NOT NULL)",
            name="ck_job_outbox_events_lock_state",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["processing_jobs.job_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_job_outbox_events_job_id", "job_outbox_events", ["job_id"], unique=True)
    op.create_index("ix_job_outbox_events_pending", "job_outbox_events", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_job_outbox_events_pending", table_name="job_outbox_events")
    op.drop_index("uq_job_outbox_events_job_id", table_name="job_outbox_events")
    op.drop_table("job_outbox_events")
    op.drop_index(
        "uq_meeting_submission_idempotency_owner_operation_key",
        table_name="meeting_submission_idempotency",
    )
    op.drop_table("meeting_submission_idempotency")
