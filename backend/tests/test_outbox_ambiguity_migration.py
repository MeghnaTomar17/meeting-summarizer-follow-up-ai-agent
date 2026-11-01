"""Schema contracts for the separate outbox ambiguity recovery counter."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from shared.database.models.job_outbox_event import JobOutboxEvent


class OutboxAmbiguityMigrationTests(unittest.TestCase):
    def test_model_has_nonnegative_separate_counter(self) -> None:
        column = JobOutboxEvent.__table__.c.ambiguity_recovery_count
        self.assertFalse(column.nullable)
        self.assertEqual(str(column.server_default.arg), "0")
        constraints = {
            constraint.name: str(getattr(constraint, "sqltext", ""))
            for constraint in JobOutboxEvent.__table__.constraints
        }
        self.assertIn("ck_job_outbox_events_ambiguity_recovery_count", constraints)
        self.assertIn("ambiguity_recovery_count >= 0", constraints["ck_job_outbox_events_ambiguity_recovery_count"])

    def test_migration_adds_and_drops_counter_without_changing_status_constraint(self) -> None:
        migration_path = (
            BACKEND_ROOT / "migrations" / "versions" / "0010_outbox_ambiguous_recovery.py"
        )
        migration = migration_path.read_text(encoding="utf-8")
        self.assertIn('revision: str = "0010_outbox_ambiguous_recovery"', migration)
        self.assertIn('down_revision: Union[str, None] = "0009_atomic_meeting_submission"', migration)
        self.assertIn('sa.Column("ambiguity_recovery_count", sa.Integer(), server_default="0", nullable=False)', migration)
        self.assertIn('"ambiguity_recovery_count >= 0"', migration)
        prior_migration = (
            BACKEND_ROOT / "migrations" / "versions" / "0009_atomic_meeting_submission.py"
        ).read_text(encoding="utf-8")
        self.assertIn("status IN ('pending', 'published')", prior_migration)


if __name__ == "__main__":
    unittest.main()
