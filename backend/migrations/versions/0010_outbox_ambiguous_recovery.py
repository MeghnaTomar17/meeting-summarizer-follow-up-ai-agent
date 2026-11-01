"""Track the separate bounded outbox ambiguity recovery allowance.

Revision ID: 0010_outbox_ambiguous_recovery
Revises: 0009_atomic_meeting_submission
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010_outbox_ambiguous_recovery"
down_revision: Union[str, None] = "0009_atomic_meeting_submission"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "job_outbox_events",
        sa.Column("ambiguity_recovery_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        "ck_job_outbox_events_ambiguity_recovery_count",
        "job_outbox_events",
        "ambiguity_recovery_count >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_job_outbox_events_ambiguity_recovery_count",
        "job_outbox_events",
        type_="check",
    )
    op.drop_column("job_outbox_events", "ambiguity_recovery_count")
