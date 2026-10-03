"""Create durable AI processing job lifecycle records.

Revision ID: 0006_processing_jobs
Revises: 0005_meeting_insights
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0006_processing_jobs"
down_revision: Union[str, None] = "0005_meeting_insights"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "processing_jobs",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transcript_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_operations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("failure_category", sa.String(length=40), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'partial', 'failed')",
            name="ck_processing_jobs_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts >= 1 AND attempt_count <= max_attempts",
            name="ck_processing_jobs_attempts",
        ),
        sa.CheckConstraint(
            "CASE WHEN jsonb_typeof(requested_operations) = 'array' THEN jsonb_array_length(requested_operations) > 0 ELSE false END",
            name="ck_processing_jobs_operations_array",
        ),
        sa.CheckConstraint(
            "(status = 'running' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL AND completed_at IS NULL) OR (status <> 'running' AND lease_token IS NULL AND lease_expires_at IS NULL)",
            name="ck_processing_jobs_lease_state",
        ),
        sa.CheckConstraint(
            "(status IN ('completed', 'partial', 'failed') AND completed_at IS NOT NULL) OR (status IN ('queued', 'running') AND completed_at IS NULL)",
            name="ck_processing_jobs_completion_time",
        ),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE", name="fk_processing_jobs_meeting_id_meetings"),
        sa.ForeignKeyConstraint(["transcript_id"], ["transcripts.id"], ondelete="CASCADE", name="fk_processing_jobs_transcript_id_transcripts"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT", name="fk_processing_jobs_owner_id_users"),
        sa.PrimaryKeyConstraint("job_id", name="pk_processing_jobs"),
    )
    op.create_index("ix_processing_jobs_status_created_at", "processing_jobs", ["status", "created_at"])
    op.create_index("ix_processing_jobs_owner_created_at", "processing_jobs", ["owner_id", "created_at"])
    op.create_index("ix_processing_jobs_meeting_id", "processing_jobs", ["meeting_id"])


def downgrade() -> None:
    op.drop_index("ix_processing_jobs_meeting_id", table_name="processing_jobs")
    op.drop_index("ix_processing_jobs_owner_created_at", table_name="processing_jobs")
    op.drop_index("ix_processing_jobs_status_created_at", table_name="processing_jobs")
    op.drop_table("processing_jobs")
