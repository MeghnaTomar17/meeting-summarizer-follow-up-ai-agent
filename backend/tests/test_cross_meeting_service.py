"""Application mapping, pagination, and deterministic clock tests."""

from __future__ import annotations

import asyncio
import importlib
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MEETING_ROOT = BACKEND_ROOT / "meeting-service"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _load_service():
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    while str(MEETING_ROOT) in sys.path:
        sys.path.remove(str(MEETING_ROOT))
    sys.path.insert(0, str(MEETING_ROOT))
    return importlib.import_module("app.services.cross_meeting_service").CrossMeetingService


class CrossMeetingServiceTests(unittest.TestCase):
    def test_service_maps_only_selected_fields_and_uses_injected_clock(self):
        Service = _load_service()
        from shared.schemas.cross_meeting import CrossMeetingDataQuery, StructuredTaskFilter

        now = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
        meeting_id, task_id, decision_id, insight_id = (uuid.uuid4() for _ in range(4))
        repository = SimpleNamespace(
            list_meetings=AsyncMock(return_value=([
                SimpleNamespace(id=meeting_id, title="Project Atlas", description="Launch", scheduled_at=now, created_at=now, organization_id=uuid.uuid4(), created_by=uuid.uuid4())
            ], 1)),
            list_tasks=AsyncMock(return_value=([
                SimpleNamespace(id=task_id, meeting_id=meeting_id, title="Review", description=None, status="in_progress", due_at=now, created_at=now, assignee_id=uuid.uuid4())
            ], 1)),
            list_decisions=AsyncMock(return_value=([
                SimpleNamespace(id=decision_id, meeting_id=meeting_id, statement="Proceed", context=None, participants=[], created_at=now)
            ], 1)),
            list_insights=AsyncMock(return_value=([
                SimpleNamespace(id=insight_id, meeting_id=meeting_id, category="risk", title="Delay", description="Vendor review is late", created_at=now)
            ], 1)),
        )
        service = Service(repository, clock=lambda: now)
        query = CrossMeetingDataQuery(
            since=now, task_filter=StructuredTaskFilter.OVERDUE, page=2, page_size=5
        )
        owner_id = uuid.uuid4()

        result = asyncio.run(service.query(query, owner_id=owner_id))

        self.assertEqual(result.meetings.items[0].id, meeting_id)
        self.assertEqual(result.tasks.items[0].id, task_id)
        self.assertEqual(result.tasks.items[0].meeting_id, meeting_id)
        self.assertEqual(result.decisions.items[0].id, decision_id)
        self.assertEqual(result.insights.items[0].id, insight_id)
        self.assertEqual(result.tasks.pagination.page, 2)
        self.assertEqual(result.tasks.pagination.total, 1)
        repository.list_meetings.assert_awaited_once_with(
            owner_id, since=now, until=None, page=2, page_size=5
        )
        repository.list_tasks.assert_awaited_once_with(
            owner_id, since=now, until=None, page=2, page_size=5,
            task_filter=StructuredTaskFilter.OVERDUE, as_of=now,
        )
        self.assertNotIn("assignee_id", result.tasks.items[0].model_dump())

    def test_query_rejects_naive_or_reversed_time_windows_and_out_of_range_pages(self):
        from pydantic import ValidationError
        from shared.schemas.cross_meeting import CrossMeetingDataQuery

        with self.assertRaises(ValidationError):
            CrossMeetingDataQuery(since=datetime(2026, 1, 1))
        with self.assertRaises(ValidationError):
            CrossMeetingDataQuery(
                since=datetime(2026, 2, 1, tzinfo=timezone.utc),
                until=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        with self.assertRaises(ValidationError):
            CrossMeetingDataQuery(page_size=101)
        with self.assertRaises(ValidationError):
            CrossMeetingDataQuery(owner_id=str(uuid.uuid4()))


if __name__ == "__main__":
    unittest.main()
