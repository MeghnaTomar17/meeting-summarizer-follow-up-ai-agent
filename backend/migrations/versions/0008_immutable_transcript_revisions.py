"""Allow immutable, ordered transcript revisions per meeting.

Revision ID: 0008_transcript_revisions
Revises: 0007_organizations_memberships
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008_transcript_revisions"
down_revision: Union[str, None] = "0007_organizations_memberships"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing transcript IDs are retained as revision 1 so durable jobs keep
    # resolving the exact transcript they were registered against.
    op.add_column(
        "transcripts",
        sa.Column("revision_number", sa.Integer(), server_default="1", nullable=False),
    )
    op.drop_index("ix_transcripts_meeting_id", table_name="transcripts")
    op.create_index("ix_transcripts_meeting_id", "transcripts", ["meeting_id"])
    op.create_unique_constraint(
        "uq_transcripts_meeting_revision", "transcripts", ["meeting_id", "revision_number"]
    )


def downgrade() -> None:
    # Downgrade is safe only when no meeting has accumulated multiple revisions.
    bind = op.get_bind()
    duplicate = bind.execute(
        sa.text(
            "SELECT meeting_id FROM transcripts GROUP BY meeting_id "
            "HAVING count(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "Cannot downgrade transcript revisions while meetings have multiple revisions."
        )

    op.drop_constraint("uq_transcripts_meeting_revision", "transcripts", type_="unique")
    op.drop_index("ix_transcripts_meeting_id", table_name="transcripts")
    op.create_index("ix_transcripts_meeting_id", "transcripts", ["meeting_id"], unique=True)
    op.drop_column("transcripts", "revision_number")
