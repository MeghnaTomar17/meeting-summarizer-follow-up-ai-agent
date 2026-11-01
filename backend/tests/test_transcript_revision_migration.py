"""Schema contract checks for immutable transcript revisions."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from shared.database.models.transcript import Transcript
from shared.database.models.meeting import Meeting


class TranscriptRevisionSchemaTestCase(unittest.TestCase):
    def test_revision_number_is_non_null_and_unique_per_meeting(self) -> None:
        table = Transcript.__table__
        self.assertIn("revision_number", table.c)
        self.assertFalse(table.c.revision_number.nullable)
        self.assertFalse(table.c.meeting_id.unique)
        unique_columns = {
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }
        self.assertIn(("meeting_id", "revision_number"), unique_columns)
        self.assertTrue(Meeting.transcripts.property.uselist)

    def test_migration_backfills_existing_rows_and_guards_lossy_downgrade(self) -> None:
        migration = (
            BACKEND_ROOT
            / "migrations"
            / "versions"
            / "0008_immutable_transcript_revisions.py"
        ).read_text(encoding="utf-8")
        self.assertIn('revision: str = "0008_transcript_revisions"', migration)
        self.assertIn('down_revision: Union[str, None] = "0007_organizations_memberships"', migration)
        self.assertIn('sa.Column("revision_number", sa.Integer(), server_default="1", nullable=False)', migration)
        self.assertIn('"uq_transcripts_meeting_revision"', migration)
        self.assertIn("HAVING count(*) > 1 LIMIT 1", migration)
        self.assertIn("Cannot downgrade transcript revisions", migration)


if __name__ == "__main__":
    unittest.main()
