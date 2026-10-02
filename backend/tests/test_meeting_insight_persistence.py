"""Model, migration-structure, and repository tests for MeetingInsight."""

from __future__ import annotations

import asyncio
import importlib.util
import io
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import configure_mappers

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MEETING_ROOT = BACKEND_ROOT / "meeting-service"
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _load_repository():
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    while str(MEETING_ROOT) in sys.path:
        sys.path.remove(str(MEETING_ROOT))
    sys.path.insert(0, str(MEETING_ROOT))
    from app.repositories.meeting_insight_repository import MeetingInsightRepository

    return MeetingInsightRepository


class MeetingInsightModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import shared.database.models  # noqa: F401

        configure_mappers()
        from shared.database.base import Base
        from shared.database.models.meeting import Meeting
        from shared.database.models.meeting_insight import MeetingInsight
        from shared.schemas.meeting_insight import InsightCategory, MeetingInsightBase

        cls.Base = Base
        cls.Meeting = Meeting
        cls.Model = MeetingInsight
        cls.InsightCategory = InsightCategory
        cls.MeetingInsightBase = MeetingInsightBase

    def test_required_columns_uuid_category_and_created_timestamp(self) -> None:
        table = self.Model.__table__
        self.assertEqual(
            {"id", "meeting_id", "category", "title", "description", "created_at"},
            set(table.columns.keys()),
        )
        self.assertEqual([column.name for column in table.primary_key], ["id"])
        self.assertEqual(table.c.id.type.__class__.__name__, "UUID")
        self.assertEqual(
            table.c.category.type.enums,
            [
                "risk", "blocker", "concern", "opportunity", "dependency",
                "unresolved", "disagreement", "observation",
            ],
        )
        self.assertEqual(table.c.category.type.name, "meeting_insight_category")
        for name in ("meeting_id", "category", "title", "description", "created_at"):
            self.assertFalse(table.c[name].nullable)
        self.assertEqual(str(table.c.created_at.server_default.arg), "now()")
        self.assertNotIn("updated_at", table.c)

    def test_meeting_relationship_is_one_to_many_and_cascades_delete(self) -> None:
        relationship = self.Meeting.insights.property
        self.assertTrue(relationship.uselist)
        self.assertIn("delete-orphan", relationship.cascade)
        self.assertEqual(self.Model.meeting.property.back_populates, "insights")
        foreign_key = next(iter(self.Model.__table__.foreign_keys))
        self.assertEqual(foreign_key.target_fullname, "meetings.id")
        self.assertEqual(foreign_key.ondelete, "CASCADE")

    def test_meeting_index_matches_meeting_scoped_query_without_speculation(self) -> None:
        self.assertEqual(
            {index.name for index in self.Model.__table__.indexes},
            {"ix_meeting_insights_meeting_id"},
        )
        index = next(iter(self.Model.__table__.indexes))
        self.assertEqual(index.columns.keys(), ["meeting_id"])

    def test_category_contract_is_shared_controlled_and_text_is_required(self) -> None:
        self.assertEqual(
            [item.value for item in self.InsightCategory],
            self.Model.__table__.c.category.type.enums,
        )
        value = self.MeetingInsightBase(
            meeting_id=str(uuid.uuid4()),
            category="risk",
            title="Delivery risk",
            description="The deadline depends on an unconfirmed review.",
        )
        self.assertIs(value.category, self.InsightCategory.RISK)
        with self.assertRaises(ValueError):
            self.MeetingInsightBase(
                meeting_id=str(uuid.uuid4()),
                category="unsupported",
                title="Title",
                description="Description",
            )
        with self.assertRaises(ValueError):
            self.MeetingInsightBase(
                meeting_id=str(uuid.uuid4()),
                category="risk",
                title=" ",
                description="Description",
            )

    def test_rows_allow_multiple_and_duplicate_looking_insights(self) -> None:
        meeting_id = uuid.uuid4()
        rows = [
            self.Model(
                id=uuid.uuid4(), meeting_id=meeting_id,
                category=self.InsightCategory.RISK,
                title="Review may slip", description="The review is not scheduled.",
            )
            for _ in range(2)
        ]
        self.assertEqual(rows[0].meeting_id, rows[1].meeting_id)
        self.assertNotEqual(rows[0].id, rows[1].id)
        self.assertFalse(
            any(constraint.__class__.__name__ == "UniqueConstraint"
                for constraint in self.Model.__table__.constraints)
        )

    def test_migration_is_chained_and_generates_reversible_postgresql_ddl(self) -> None:
        migration_path = BACKEND_ROOT / "migrations" / "versions" / "0005_meeting_insights.py"
        spec = importlib.util.spec_from_file_location("meeting_insight_migration", migration_path)
        self.assertIsNotNone(spec)
        migration = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(migration)
        self.assertEqual(migration.revision, "0005_meeting_insights")
        self.assertEqual(migration.down_revision, "0004_meeting_domain_results")
        self.assertEqual(migration.meeting_insight_category.name, "meeting_insight_category")
        self.assertEqual(
            migration.meeting_insight_category.enums,
            [item.value for item in self.InsightCategory],
        )

        statements = io.StringIO()
        context = MigrationContext.configure(
            dialect_name="postgresql", opts={"as_sql": True, "output_buffer": statements}
        )
        # Enum existence is handled by Alembic in a live migration. In this
        # offline DDL test, capture table/index SQL without connecting to a DB.
        enum_type = migration.meeting_insight_category
        original_create, original_drop = enum_type.create, enum_type.drop
        enum_calls: list[tuple[str, bool]] = []
        enum_type.create = lambda *args, **kwargs: enum_calls.append(
            ("create", kwargs["checkfirst"])
        )
        enum_type.drop = lambda *args, **kwargs: enum_calls.append(
            ("drop", kwargs["checkfirst"])
        )
        try:
            with Operations.context(context):
                migration.upgrade()
            with Operations.context(context):
                migration.downgrade()
        finally:
            enum_type.create, enum_type.drop = original_create, original_drop

        ddl = statements.getvalue()
        self.assertIn("CREATE TABLE meeting_insights", ddl)
        self.assertIn("DROP TABLE meeting_insights", ddl)
        self.assertIn("fk_meeting_insights_meeting_id_meetings", ddl)
        self.assertIn("ON DELETE CASCADE", ddl)
        self.assertIn("PRIMARY KEY (id)", ddl)
        self.assertIn("category meeting_insight_category NOT NULL", ddl)
        self.assertIn("ix_meeting_insights_meeting_id", ddl)
        self.assertIn("DROP INDEX ix_meeting_insights_meeting_id", ddl)
        self.assertEqual(enum_calls, [("create", True), ("drop", True)])


class MeetingInsightRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.Repository = _load_repository()
        self.session = MagicMock(spec=AsyncSession)
        self.session.flush = AsyncMock()
        self.session.execute = AsyncMock()
        from shared.database.models.meeting_insight import MeetingInsight
        from shared.schemas.meeting_insight import InsightCategory

        self.Model = MeetingInsight
        self.Category = InsightCategory

    def _assert_no_transaction_control(self) -> None:
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()

    def test_create_adds_flushes_and_does_not_commit(self) -> None:
        insight = self.Model(
            id=uuid.uuid4(), meeting_id=uuid.uuid4(), category=self.Category.BLOCKER,
            title="Review blocked", description="The reviewer is unavailable.",
        )
        created = asyncio.run(self.Repository(self.session).create(insight))
        self.assertIs(created, insight)
        self.session.add.assert_called_once_with(insight)
        self.session.flush.assert_awaited_once()
        self._assert_no_transaction_control()

    def test_get_by_id_filters_by_id(self) -> None:
        insight_id = uuid.uuid4()
        expected = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = expected
        self.session.execute.return_value = result
        found = asyncio.run(self.Repository(self.session).get_by_id(insight_id))
        self.assertIs(found, expected)
        statement = self.session.execute.await_args.args[0]
        self.assertIn("WHERE meeting_insights.id", str(statement))
        self.assertIn(insight_id, statement.compile().params.values())
        self._assert_no_transaction_control()

    def test_list_is_meeting_scoped_and_deterministically_ordered(self) -> None:
        meeting_id = uuid.uuid4()
        expected = [MagicMock(), MagicMock()]
        result = MagicMock()
        result.scalars.return_value.all.return_value = expected
        self.session.execute.return_value = result
        found = asyncio.run(self.Repository(self.session).list_by_meeting_id(meeting_id))
        self.assertEqual(found, expected)
        statement = self.session.execute.await_args.args[0]
        self.assertIn("WHERE meeting_insights.meeting_id", str(statement))
        self.assertIn(
            "ORDER BY meeting_insights.created_at ASC, meeting_insights.id ASC",
            str(statement),
        )
        self.assertIn(meeting_id, statement.compile().params.values())
        self._assert_no_transaction_control()

    def test_empty_result_represents_zero_insights(self) -> None:
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        self.session.execute.return_value = result
        found = asyncio.run(
            self.Repository(self.session).list_by_meeting_id(uuid.uuid4())
        )
        self.assertEqual(found, [])
        self._assert_no_transaction_control()


if __name__ == "__main__":
    unittest.main()
