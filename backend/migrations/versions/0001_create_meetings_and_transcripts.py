"""Create meetings and transcripts.

Revision ID: 0001_meetings_transcripts
Revises:
Create Date: 2026-09-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0001_meetings_transcripts"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


meeting_status = postgresql.ENUM(
    "pending",
    "processing",
    "ready",
    "failed",
    name="meeting_status",
    create_type=False,
)


def upgrade() -> None:
    meeting_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "meetings",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("participants", postgresql.JSONB(), nullable=False),
        sa.Column(
            "status",
            meeting_status,
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_meetings_organization_id", "meetings", ["organization_id"])
    op.create_index("ix_meetings_created_by", "meetings", ["created_by"])

    op.create_table(
        "transcripts",
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("segments", postgresql.JSONB(), nullable=False),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_transcripts_meeting_id",
        "transcripts",
        ["meeting_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_transcripts_meeting_id", table_name="transcripts")
    op.drop_table("transcripts")
    op.drop_index("ix_meetings_created_by", table_name="meetings")
    op.drop_index("ix_meetings_organization_id", table_name="meetings")
    op.drop_table("meetings")
    meeting_status.drop(op.get_bind(), checkfirst=True)
