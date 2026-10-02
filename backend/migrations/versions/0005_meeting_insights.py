"""Persist individual MeetingInsight candidates.

Revision ID: 0005_meeting_insights
Revises: 0004_meeting_domain_results
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0005_meeting_insights"
down_revision: Union[str, None] = "0004_meeting_domain_results"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


meeting_insight_category = postgresql.ENUM(
    "risk",
    "blocker",
    "concern",
    "opportunity",
    "dependency",
    "unresolved",
    "disagreement",
    "observation",
    name="meeting_insight_category",
    create_type=False,
)


def upgrade() -> None:
    meeting_insight_category.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "meeting_insights",
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category", meeting_insight_category, nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
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
            name="fk_meeting_insights_meeting_id_meetings",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_meeting_insights_meeting_id", "meeting_insights", ["meeting_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_meeting_insights_meeting_id", table_name="meeting_insights")
    op.drop_table("meeting_insights")
    meeting_insight_category.drop(op.get_bind(), checkfirst=True)
