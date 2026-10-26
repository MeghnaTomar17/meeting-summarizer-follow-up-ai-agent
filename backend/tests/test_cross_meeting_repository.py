"""SQL ownership and filter contract tests for structured cross-meeting queries."""

from __future__ import annotations

import asyncio
import importlib
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MEETING_ROOT = BACKEND_ROOT / "meeting-service"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _load_repository():
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    while str(MEETING_ROOT) in sys.path:
        sys.path.remove(str(MEETING_ROOT))
    sys.path.insert(0, str(MEETING_ROOT))
    return importlib.import_module(
        "app.repositories.cross_meeting_repository"
    ).CrossMeetingRepository


class CrossMeetingRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.Repository = _load_repository()
        self.session = MagicMock()
        self.session.execute = AsyncMock()
        self.repository = self.Repository(self.session)
        self.owner_id = uuid.uuid4()
        self.as_of = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)

    def _execute_queries(self, method, **kwargs):
        rows = MagicMock()
        rows.scalars.return_value.all.return_value = []
        count = MagicMock()
        count.scalar_one.return_value = 0
        self.session.execute.side_effect = [rows, count]
        asyncio.run(method(self.owner_id, page=2, page_size=5, **kwargs))
        return self.session.execute.await_args_list[0].args[0], self.session.execute.await_args_list[1].args[0]

    def test_child_queries_join_owner_meeting_and_apply_bounded_stable_paging(self):
        since = datetime(2026, 10, 1, tzinfo=timezone.utc)
        until = datetime(2026, 11, 1, tzinfo=timezone.utc)
        statement, count_statement = self._execute_queries(
            self.repository.list_decisions, since=since, until=until
        )
        sql = str(statement)
        self.assertIn("JOIN meetings ON decisions.meeting_id = meetings.id", sql)
        self.assertIn("meetings.created_by", sql)
        self.assertIn("decisions.created_at >=", sql)
        self.assertIn("decisions.created_at <", sql)
        self.assertIn("SELECT DISTINCT", sql)
        self.assertIn("ORDER BY decisions.created_at DESC, decisions.id DESC", sql)
        self.assertIn("LIMIT", sql)
        self.assertIn("OFFSET", sql)
        self.assertIn("count(distinct(decisions.id))", str(count_statement).lower())
        self.assertIn(self.owner_id, statement.compile().params.values())
        self.assertIn(5, statement.compile().params.values())

    def test_unresolved_filter_is_exactly_open_and_in_progress(self):
        from shared.schemas.cross_meeting import StructuredTaskFilter

        statement, _ = self._execute_queries(
            self.repository.list_tasks,
            since=None, until=None,
            task_filter=StructuredTaskFilter.UNRESOLVED, as_of=self.as_of,
        )
        sql = str(statement)
        self.assertIn("tasks.status IN", sql)
        self.assertNotIn("tasks.due_at <", sql)
        self.assertIn("open", str(statement.compile().params.values()))
        self.assertIn("in_progress", str(statement.compile().params.values()))
        self.assertIn(self.owner_id, statement.compile().params.values())

    def test_overdue_filter_uses_strict_as_of_boundary_and_excludes_terminal_statuses(self):
        from shared.schemas.cross_meeting import StructuredTaskFilter

        statement, _ = self._execute_queries(
            self.repository.list_tasks,
            since=None, until=None,
            task_filter=StructuredTaskFilter.OVERDUE, as_of=self.as_of,
        )
        sql = str(statement)
        self.assertIn("tasks.due_at IS NOT NULL", sql)
        self.assertIn("tasks.due_at <", sql)
        self.assertIn("tasks.status NOT IN", sql)
        params = statement.compile().params
        self.assertIn(self.as_of, params.values())
        self.assertIn("done", str(params.values()))
        self.assertIn("cancelled", str(params.values()))

    def test_meeting_time_filter_uses_scheduled_timestamp_and_nulls_last_order(self):
        since = datetime(2026, 10, 1, tzinfo=timezone.utc)
        statement, _ = self._execute_queries(
            self.repository.list_meetings, since=since, until=None
        )
        sql = str(statement)
        self.assertIn("meetings.scheduled_at >=", sql)
        self.assertIn("NULLS LAST", sql)
        self.assertIn(self.owner_id, statement.compile().params.values())

    def test_calendar_month_uses_inclusive_start_and_exclusive_end_on_scheduled_at(self):
        start = datetime(2026, 10, 1, tzinfo=timezone.utc)
        end = datetime(2026, 11, 1, tzinfo=timezone.utc)
        statement, _ = self._execute_queries(
            self.repository.list_meetings, since=start, until=end
        )
        sql = str(statement)
        self.assertIn("meetings.scheduled_at >=", sql)
        self.assertIn("meetings.scheduled_at <", sql)
        self.assertIn(start, statement.compile().params.values())
        self.assertIn(end, statement.compile().params.values())


if __name__ == "__main__":
    unittest.main()
