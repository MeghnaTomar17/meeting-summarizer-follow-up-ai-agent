"""Unit coverage for owner-scoped detail resources."""

from __future__ import annotations

import asyncio
import importlib
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MEETING_ROOT = BACKEND_ROOT / "meeting-service"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


class MeetingDetailServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        for key in list(sys.modules):
            if key == "app" or key.startswith("app."):
                del sys.modules[key]
        while str(MEETING_ROOT) in sys.path:
            sys.path.remove(str(MEETING_ROOT))
        sys.path.insert(0, str(MEETING_ROOT))
        from app.services.meeting_service import MeetingService

        self.owner_id = uuid.uuid4()
        self.meeting_id = uuid.uuid4()
        self.session = MagicMock()
        self.meeting_repository = MagicMock()
        self.meeting_repository.latest_processing_job = AsyncMock()
        self.transcript_repository = MagicMock()
        self.service = MeetingService(self.session, self.meeting_repository, self.transcript_repository)
        self.service.require_owned_meeting = AsyncMock(return_value=SimpleNamespace(id=self.meeting_id))
        self.service._insight_repository.list_by_meeting_id = AsyncMock(return_value=[])

    def test_insights_require_owned_meeting_and_return_pagination(self) -> None:
        result = asyncio.run(self.service.list_meeting_insights(
            str(self.meeting_id), self.owner_id, page=1, page_size=10
        ))
        self.service.require_owned_meeting.assert_awaited_once_with(str(self.meeting_id), self.owner_id)
        self.service._insight_repository.list_by_meeting_id.assert_awaited_once_with(self.meeting_id)
        self.assertEqual(result.items, [])
        self.assertEqual(result.pagination.total, 0)

    def test_processing_status_uses_owner_filtered_latest_job_or_null(self) -> None:
        self.meeting_repository.latest_processing_job.return_value = None
        result = asyncio.run(self.service.get_processing_status(str(self.meeting_id), self.owner_id))
        self.service.require_owned_meeting.assert_awaited_once_with(str(self.meeting_id), self.owner_id)
        self.meeting_repository.latest_processing_job.assert_awaited_once_with(self.meeting_id, self.owner_id)
        self.assertIsNone(result.status)

        now = datetime.now(timezone.utc)
        self.meeting_repository.latest_processing_job.return_value = SimpleNamespace(
            status="running", updated_at=now, completed_at=None
        )
        result = asyncio.run(self.service.get_processing_status(str(self.meeting_id), self.owner_id))
        self.assertEqual(result.status, "running")
        self.assertEqual(result.updated_at, now)


if __name__ == "__main__":
    unittest.main()
