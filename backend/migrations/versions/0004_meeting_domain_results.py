"""Create persistent meeting result entities.

Revision ID: 0004_meeting_domain_results
Revises: 0003_refresh_sessions
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0004_meeting_domain_results"
down_revision: Union[str, None] = "0003_refresh_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


task_status = postgresql.ENUM(
    "open",
    "in_progress",
    "done",
    "cancelled",
    name="task_status",
    create_type=False,
)
followup_status = postgresql.ENUM(
    "draft",
    "scheduled",
    "sent",
    "failed",
    name="followup_status",
    create_type=False,
)


def upgrade() -> None:
    task_status.create(op.get_bind(), checkfirst=True)
    followup_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "summaries",
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("key_topics", postgresql.JSONB(), nullable=False),
        sa.Column("model_provider", sa.Text(), nullable=True),
        sa.Column("model_name", sa.Text(), nullable=True),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["meeting_id"],
            ["meetings.id"],
            name="fk_summaries_meeting_id_meetings",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "meeting_id", "version", name="uq_summaries_meeting_version"
        ),
        sa.CheckConstraint("version >= 1", name="ck_summaries_version_positive"),
    )
    op.create_index(
        "ix_summaries_meeting_version_desc",
        "summaries",
        ["meeting_id", sa.text("version DESC")],
    )

    op.create_table(
        "tasks",
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("assignee_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            task_status,
            nullable=False,
            server_default=sa.text("'open'"),
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id"],
            ["meetings.id"],
            name="fk_tasks_meeting_id_meetings",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["assignee_id"],
            ["users.id"],
            name="fk_tasks_assignee_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tasks_meeting_status", "tasks", ["meeting_id", "status"])
    op.create_index("ix_tasks_assignee_status", "tasks", ["assignee_id", "status"])

    op.create_table(
        "decisions",
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("participants", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["meeting_id"],
            ["meetings.id"],
            name="fk_decisions_meeting_id_meetings",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_decisions_meeting_id", "decisions", ["meeting_id"])

    op.create_table(
        "followups",
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=False),
        sa.Column("recipients", postgresql.JSONB(), nullable=False),
        sa.Column(
            "status",
            followup_status,
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["meeting_id"],
            ["meetings.id"],
            name="fk_followups_meeting_id_meetings",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_followups_meeting_id", "followups", ["meeting_id"])


def downgrade() -> None:
    op.drop_index("ix_followups_meeting_id", table_name="followups")
    op.drop_table("followups")
    op.drop_index("ix_decisions_meeting_id", table_name="decisions")
    op.drop_table("decisions")
    op.drop_index("ix_tasks_assignee_status", table_name="tasks")
    op.drop_index("ix_tasks_meeting_status", table_name="tasks")
    op.drop_table("tasks")
    op.drop_index("ix_summaries_meeting_version_desc", table_name="summaries")
    op.drop_table("summaries")
    followup_status.drop(op.get_bind(), checkfirst=True)
    task_status.drop(op.get_bind(), checkfirst=True)
