"""Metadata checks for persisted Phase 5 meeting-result models."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from sqlalchemy.orm import configure_mappers


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


class Phase5DomainModelTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import shared.database.models  # noqa: F401

        configure_mappers()
        from shared.database.base import Base
        from shared.database.models import Decision, Followup, Summary, Task

        cls.Base = Base
        cls.Summary = Summary
        cls.Task = Task
        cls.Decision = Decision
        cls.Followup = Followup
        from shared.database.models.meeting import Meeting

        cls.Meeting = Meeting

    def test_models_register_expected_tables_and_uuid_primary_keys(self) -> None:
        expected = {
            "summaries",
            "tasks",
            "decisions",
            "followups",
        }
        self.assertTrue(expected.issubset(self.Base.metadata.tables))

        for table_name in expected:
            table = self.Base.metadata.tables[table_name]
            self.assertEqual([column.name for column in table.primary_key], ["id"])
            self.assertTrue(table.c.id.primary_key)
            self.assertEqual(table.c.id.type.__class__.__name__, "UUID")

    def test_summary_versioning_and_meeting_relationship(self) -> None:
        table = self.Summary.__table__
        self.assertFalse(table.c.meeting_id.nullable)
        self.assertFalse(table.c.content.nullable)
        self.assertFalse(table.c.key_topics.nullable)
        self.assertTrue(table.c.model_provider.nullable)
        self.assertTrue(table.c.model_name.nullable)
        self.assertEqual(table.c.version.default.arg, 1)
        self.assertEqual(str(table.c.version.server_default.arg), "1")
        self.assertIn(
            "uq_summaries_meeting_version",
            {constraint.name for constraint in table.constraints},
        )
        self.assertIn(
            "ck_summaries_version_positive",
            {constraint.name for constraint in table.constraints},
        )
        self.assertEqual(self.Summary.meeting.property.back_populates, "summaries")

    def test_meeting_result_relationships_are_one_to_many_and_owned(self) -> None:
        for relationship_name in ("summaries", "tasks", "decisions", "followups"):
            relationship = getattr(self.Meeting, relationship_name).property
            self.assertTrue(relationship.uselist)
            self.assertIn("delete-orphan", relationship.cascade)

    def test_task_fields_status_assignee_and_indexes(self) -> None:
        table = self.Task.__table__
        self.assertFalse(table.c.title.nullable)
        self.assertTrue(table.c.description.nullable)
        self.assertTrue(table.c.assignee_id.nullable)
        self.assertTrue(table.c.due_at.nullable)
        self.assertEqual(table.c.status.type.enums, ["open", "in_progress", "done", "cancelled"])
        self.assertEqual(table.c.status.server_default.arg, "open")
        foreign_keys = {fk.parent.name: fk for fk in table.foreign_keys}
        self.assertEqual(foreign_keys["meeting_id"].target_fullname, "meetings.id")
        self.assertEqual(foreign_keys["meeting_id"].ondelete, "CASCADE")
        self.assertEqual(foreign_keys["assignee_id"].target_fullname, "users.id")
        self.assertEqual(foreign_keys["assignee_id"].ondelete, "SET NULL")
        self.assertEqual(self.Task.assignee.property.back_populates, "assigned_tasks")
        self.assertEqual(
            {index.name for index in table.indexes},
            {"ix_tasks_meeting_status", "ix_tasks_assignee_status"},
        )

    def test_decision_and_followup_constraints_and_relationships(self) -> None:
        decision = self.Decision.__table__
        self.assertFalse(decision.c.statement.nullable)
        self.assertTrue(decision.c.context.nullable)
        self.assertFalse(decision.c.participants.nullable)
        self.assertEqual(self.Decision.meeting.property.back_populates, "decisions")
        decision_fk = next(iter(decision.foreign_keys))
        self.assertEqual(decision_fk.target_fullname, "meetings.id")
        self.assertEqual(decision_fk.ondelete, "CASCADE")

        followup = self.Followup.__table__
        self.assertFalse(followup.c.subject.nullable)
        self.assertFalse(followup.c.body_html.nullable)
        self.assertFalse(followup.c.recipients.nullable)
        self.assertTrue(followup.c.scheduled_at.nullable)
        self.assertTrue(followup.c.sent_at.nullable)
        self.assertEqual(followup.c.status.type.enums, ["draft", "scheduled", "sent", "failed"])
        self.assertEqual(followup.c.status.server_default.arg, "draft")
        self.assertEqual(self.Followup.meeting.property.back_populates, "followups")
        followup_fk = next(iter(followup.foreign_keys))
        self.assertEqual(followup_fk.target_fullname, "meetings.id")
        self.assertEqual(followup_fk.ondelete, "CASCADE")

    def test_reversible_migration_follows_refresh_sessions(self) -> None:
        migration = (
            BACKEND_ROOT
            / "migrations"
            / "versions"
            / "0004_meeting_domain_results.py"
        ).read_text(encoding="utf-8")
        self.assertIn('revision: str = "0004_meeting_domain_results"', migration)
        self.assertIn('down_revision: Union[str, None] = "0003_refresh_sessions"', migration)
        for table in ("summaries", "tasks", "decisions", "followups"):
            self.assertIn(f'op.create_table(\n        "{table}"', migration)
            self.assertIn(f'op.drop_table("{table}")', migration)


if __name__ == "__main__":
    unittest.main()
