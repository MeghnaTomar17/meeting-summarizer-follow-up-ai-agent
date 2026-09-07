"""Unit tests for meeting-service SQLAlchemy repositories."""

from __future__ import annotations

import asyncio
import importlib
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MEETING_ROOT = BACKEND_ROOT / "meeting-service"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _load_repositories():
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]
    while str(MEETING_ROOT) in sys.path:
        sys.path.remove(str(MEETING_ROOT))
    sys.path.insert(0, str(MEETING_ROOT))

    meeting_module = importlib.import_module("app.repositories.meeting_repository")
    transcript_module = importlib.import_module(
        "app.repositories.transcript_repository"
    )
    return meeting_module.MeetingRepository, transcript_module.TranscriptRepository


class RepositoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.MeetingRepository, self.TranscriptRepository = _load_repositories()
        self.session = MagicMock(spec=AsyncSession)
        self.session.flush = AsyncMock()
        self.session.execute = AsyncMock()

        from shared.database.models.meeting import Meeting, MeetingStatus
        from shared.database.models.transcript import Transcript

        self.Meeting = Meeting
        self.MeetingStatus = MeetingStatus
        self.Transcript = Transcript

    def _meeting(self) -> object:
        return self.Meeting(
            id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            created_by=uuid.uuid4(),
            title="Weekly sync",
            participants=[],
        )

    def _transcript(self) -> object:
        return self.Transcript(
            id=uuid.uuid4(),
            meeting_id=uuid.uuid4(),
            segments=[],
        )

    def test_meeting_create_adds_and_flushes_without_commit(self) -> None:
        meeting = self._meeting()
        repository = self.MeetingRepository(self.session)

        result = asyncio.run(repository.create(meeting))

        self.assertIs(result, meeting)
        self.session.add.assert_called_once_with(meeting)
        self.session.flush.assert_awaited_once()
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()

    def test_meeting_get_by_id_returns_entity_or_none(self) -> None:
        meeting = self._meeting()
        repository = self.MeetingRepository(self.session)
        result = MagicMock()
        result.scalar_one_or_none.return_value = meeting
        self.session.execute.return_value = result

        found = asyncio.run(repository.get_by_id(meeting.id))
        self.assertIs(found, meeting)

        result.scalar_one_or_none.return_value = None
        missing = asyncio.run(repository.get_by_id(uuid.uuid4()))
        self.assertIsNone(missing)
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()

    def test_meeting_list_filters_orders_and_paginates(self) -> None:
        organization_id = uuid.uuid4()
        meetings = [self._meeting(), self._meeting()]
        repository = self.MeetingRepository(self.session)
        result = MagicMock()
        result.scalars.return_value.all.return_value = meetings
        self.session.execute.return_value = result

        returned = asyncio.run(
            repository.list_by_organization(organization_id, limit=20, offset=40)
        )

        self.assertEqual(returned, meetings)
        statement = self.session.execute.await_args.args[0]
        sql = str(statement)
        self.assertIn("WHERE meetings.organization_id", sql)
        self.assertIn("ORDER BY meetings.created_at DESC, meetings.id DESC", sql)
        self.assertIn(organization_id, statement.compile().params.values())
        self.assertIn(20, statement.compile().params.values())
        self.assertIn(40, statement.compile().params.values())
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()

    def test_meeting_count_filters_by_organization_without_transaction(self) -> None:
        organization_id = uuid.uuid4()
        repository = self.MeetingRepository(self.session)
        result = MagicMock()
        result.scalar_one.return_value = 42
        self.session.execute.return_value = result

        count = asyncio.run(repository.count_by_organization(organization_id))

        self.assertEqual(count, 42)
        statement = self.session.execute.await_args.args[0]
        sql = str(statement)
        self.assertIn("FROM meetings", sql)
        self.assertIn("WHERE meetings.organization_id", sql)
        self.assertIn(organization_id, statement.compile().params.values())
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()

    def test_meeting_update_flushes_and_returns_supplied_entity(self) -> None:
        meeting = self._meeting()
        meeting.title = "Updated weekly sync"
        repository = self.MeetingRepository(self.session)

        updated = asyncio.run(repository.update(meeting))

        self.assertIs(updated, meeting)
        self.assertEqual(updated.title, "Updated weekly sync")
        self.session.flush.assert_awaited_once()
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()

    def test_meeting_update_status_flushes_without_commit(self) -> None:
        meeting = self._meeting()
        repository = self.MeetingRepository(self.session)

        result = asyncio.run(
            repository.update_status(meeting, self.MeetingStatus.READY)
        )

        self.assertIs(result, meeting)
        self.assertEqual(meeting.status, self.MeetingStatus.READY)
        self.session.flush.assert_awaited_once()
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()

    def test_transcript_create_adds_and_flushes_without_commit(self) -> None:
        transcript = self._transcript()
        repository = self.TranscriptRepository(self.session)

        result = asyncio.run(repository.create(transcript))

        self.assertIs(result, transcript)
        self.session.add.assert_called_once_with(transcript)
        self.session.flush.assert_awaited_once()
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()

    def test_transcript_get_by_meeting_id_returns_entity_or_none(self) -> None:
        transcript = self._transcript()
        repository = self.TranscriptRepository(self.session)
        result = MagicMock()
        result.scalar_one_or_none.return_value = transcript
        self.session.execute.return_value = result

        found = asyncio.run(repository.get_by_meeting_id(transcript.meeting_id))
        self.assertIs(found, transcript)

        result.scalar_one_or_none.return_value = None
        missing = asyncio.run(repository.get_by_meeting_id(uuid.uuid4()))
        self.assertIsNone(missing)
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()

    def test_transcript_replace_segments_and_language_without_commit(self) -> None:
        transcript = self._transcript()
        repository = self.TranscriptRepository(self.session)
        segments = [{"index": 0, "text": "Decide next steps."}]

        result = asyncio.run(
            repository.replace_for_meeting(
                transcript,
                segments=segments,
                language="en",
            )
        )

        self.assertIs(result, transcript)
        self.assertEqual(transcript.segments, segments)
        self.assertEqual(transcript.language, "en")
        self.session.flush.assert_awaited_once()
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
