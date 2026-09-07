"""Unit tests for meeting-service use cases."""

from __future__ import annotations

import asyncio
import importlib
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MEETING_ROOT = BACKEND_ROOT / "meeting-service"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _load_service():
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]
    while str(MEETING_ROOT) in sys.path:
        sys.path.remove(str(MEETING_ROOT))
    sys.path.insert(0, str(MEETING_ROOT))
    return importlib.import_module("app.services.meeting_service").MeetingService


class MeetingServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.MeetingService = _load_service()

        from app.repositories.meeting_repository import MeetingRepository
        from app.repositories.transcript_repository import TranscriptRepository
        from shared.database.models.meeting import Meeting, MeetingStatus as ORMMeetingStatus
        from shared.database.models.transcript import Transcript
        from shared.exceptions.common import ConflictError, NotFoundError
        from shared.exceptions.common import ValidationError as AppValidationError
        from shared.schemas.meeting import MeetingCreate, MeetingStatus
        from shared.schemas.transcript import TranscriptBase, TranscriptSegment

        self.Meeting = Meeting
        self.ORMMeetingStatus = ORMMeetingStatus
        self.Transcript = Transcript
        self.ConflictError = ConflictError
        self.NotFoundError = NotFoundError
        self.AppValidationError = AppValidationError
        self.MeetingCreate = MeetingCreate
        self.MeetingStatus = MeetingStatus
        self.TranscriptBase = TranscriptBase
        self.TranscriptSegment = TranscriptSegment

        self.session = MagicMock(spec=AsyncSession)
        self.session.commit = AsyncMock()
        self.meeting_repository = MagicMock(spec=MeetingRepository)
        self.transcript_repository = MagicMock(spec=TranscriptRepository)
        self.meeting_repository.create = AsyncMock()
        self.meeting_repository.get_by_id = AsyncMock()
        self.meeting_repository.list_by_organization = AsyncMock()
        self.meeting_repository.update_status = AsyncMock()
        self.transcript_repository.create = AsyncMock()
        self.transcript_repository.get_by_meeting_id = AsyncMock()
        self.transcript_repository.replace_for_meeting = AsyncMock()
        self.service = self.MeetingService(
            self.session,
            self.meeting_repository,
            self.transcript_repository,
        )

    def _meeting(self) -> object:
        now = datetime.now(timezone.utc)
        return self.Meeting(
            id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            created_by=uuid.uuid4(),
            title="Weekly sync",
            participants=["alice@example.com"],
            status=self.ORMMeetingStatus.PENDING,
            created_at=now,
            updated_at=now,
        )

    def _transcript(self, meeting_id: uuid.UUID | None = None) -> object:
        now = datetime.now(timezone.utc)
        return self.Transcript(
            id=uuid.uuid4(),
            meeting_id=meeting_id or uuid.uuid4(),
            segments=[{"index": 0, "text": "Plan the release."}],
            language="en",
            created_at=now,
            updated_at=now,
        )

    def test_create_meeting_maps_payload_and_commits_once(self) -> None:
        organization_id = uuid.uuid4()
        created_by = uuid.uuid4()
        created = self._meeting()
        self.meeting_repository.create.return_value = created
        payload = self.MeetingCreate(
            organization_id=str(organization_id),
            created_by=str(created_by),
            title="Planning",
            description="Q4 planning",
            participants=["alice@example.com"],
        )

        result = asyncio.run(self.service.create_meeting(payload))

        submitted = self.meeting_repository.create.await_args.args[0]
        self.assertEqual(submitted.organization_id, organization_id)
        self.assertEqual(submitted.created_by, created_by)
        self.assertEqual(submitted.status, self.ORMMeetingStatus.PENDING)
        self.assertEqual(submitted.participants, ["alice@example.com"])
        self.assertEqual(result.id, str(created.id))
        self.session.commit.assert_awaited_once()

    def test_invalid_meeting_uuid_raises_validation_error_without_commit(self) -> None:
        payload = self.MeetingCreate(
            organization_id="not-a-uuid",
            created_by=str(uuid.uuid4()),
            title="Planning",
        )

        with self.assertRaises(self.AppValidationError):
            asyncio.run(self.service.create_meeting(payload))

        self.meeting_repository.create.assert_not_called()
        self.session.commit.assert_not_called()

    def test_get_meeting_returns_public_dto_without_commit(self) -> None:
        meeting = self._meeting()
        self.meeting_repository.get_by_id.return_value = meeting

        result = asyncio.run(self.service.get_meeting(str(meeting.id)))

        self.assertEqual(result.id, str(meeting.id))
        self.assertEqual(result.status, self.MeetingStatus.PENDING)
        self.meeting_repository.get_by_id.assert_awaited_once_with(meeting.id)
        self.session.commit.assert_not_called()

    def test_get_missing_meeting_raises_not_found_without_commit(self) -> None:
        self.meeting_repository.get_by_id.return_value = None

        with self.assertRaises(self.NotFoundError):
            asyncio.run(self.service.get_meeting(str(uuid.uuid4())))

        self.session.commit.assert_not_called()

    def test_list_meetings_passes_pagination_and_does_not_commit(self) -> None:
        organization_id = uuid.uuid4()
        self.meeting_repository.list_by_organization.return_value = [self._meeting()]

        results = asyncio.run(
            self.service.list_meetings(str(organization_id), limit=20, offset=40)
        )

        self.assertEqual(len(results), 1)
        self.meeting_repository.list_by_organization.assert_awaited_once_with(
            organization_id,
            limit=20,
            offset=40,
        )
        self.session.commit.assert_not_called()

    def test_update_status_maps_enum_and_commits_once(self) -> None:
        meeting = self._meeting()
        meeting.status = self.ORMMeetingStatus.READY
        self.meeting_repository.get_by_id.return_value = meeting
        self.meeting_repository.update_status.return_value = meeting

        result = asyncio.run(
            self.service.update_meeting_status(
                str(meeting.id),
                self.MeetingStatus.READY,
            )
        )

        self.meeting_repository.update_status.assert_awaited_once_with(
            meeting,
            self.ORMMeetingStatus.READY,
        )
        self.assertEqual(result.status, self.MeetingStatus.READY)
        self.session.commit.assert_awaited_once()

    def test_update_status_missing_meeting_does_not_commit(self) -> None:
        self.meeting_repository.get_by_id.return_value = None

        with self.assertRaises(self.NotFoundError):
            asyncio.run(
                self.service.update_meeting_status(
                    str(uuid.uuid4()),
                    self.MeetingStatus.READY,
                )
            )

        self.meeting_repository.update_status.assert_not_called()
        self.session.commit.assert_not_called()

    def test_create_transcript_converts_segments_and_commits_once(self) -> None:
        meeting = self._meeting()
        created = self._transcript(meeting.id)
        self.meeting_repository.get_by_id.return_value = meeting
        self.transcript_repository.get_by_meeting_id.return_value = None
        self.transcript_repository.create.return_value = created
        payload = self.TranscriptBase(
            meeting_id=str(meeting.id),
            segments=[self.TranscriptSegment(index=0, text="Plan the release.")],
            language="en",
        )

        result = asyncio.run(self.service.create_transcript(payload))

        submitted = self.transcript_repository.create.await_args.args[0]
        self.assertEqual(submitted.meeting_id, meeting.id)
        self.assertEqual(submitted.segments, [{"index": 0, "speaker": None, "text": "Plan the release.", "start_ms": None, "end_ms": None}])
        self.assertEqual(result.id, str(created.id))
        self.session.commit.assert_awaited_once()

    def test_create_transcript_missing_meeting_does_not_commit(self) -> None:
        self.meeting_repository.get_by_id.return_value = None
        payload = self.TranscriptBase(meeting_id=str(uuid.uuid4()))

        with self.assertRaises(self.NotFoundError):
            asyncio.run(self.service.create_transcript(payload))

        self.transcript_repository.get_by_meeting_id.assert_not_called()
        self.session.commit.assert_not_called()

    def test_create_transcript_duplicate_raises_conflict_without_commit(self) -> None:
        meeting = self._meeting()
        self.meeting_repository.get_by_id.return_value = meeting
        self.transcript_repository.get_by_meeting_id.return_value = self._transcript(
            meeting.id
        )
        payload = self.TranscriptBase(meeting_id=str(meeting.id))

        with self.assertRaises(self.ConflictError):
            asyncio.run(self.service.create_transcript(payload))

        self.transcript_repository.create.assert_not_called()
        self.session.commit.assert_not_called()

    def test_get_transcript_and_missing_transcript_do_not_commit(self) -> None:
        transcript = self._transcript()
        self.transcript_repository.get_by_meeting_id.return_value = transcript

        result = asyncio.run(self.service.get_transcript(str(transcript.meeting_id)))
        self.assertEqual(result.id, str(transcript.id))
        self.session.commit.assert_not_called()

        self.transcript_repository.get_by_meeting_id.return_value = None
        with self.assertRaises(self.NotFoundError):
            asyncio.run(self.service.get_transcript(str(uuid.uuid4())))
        self.session.commit.assert_not_called()

    def test_replace_transcript_maps_segments_and_commits_once(self) -> None:
        transcript = self._transcript()
        updated = self._transcript(transcript.meeting_id)
        updated.segments = [{"index": 1, "text": "Ship next week."}]
        updated.language = "fr"
        self.transcript_repository.get_by_meeting_id.return_value = transcript
        self.transcript_repository.replace_for_meeting.return_value = updated
        segments = [self.TranscriptSegment(index=1, text="Ship next week.")]

        result = asyncio.run(
            self.service.replace_transcript(
                str(transcript.meeting_id),
                segments=segments,
                language="fr",
            )
        )

        self.transcript_repository.replace_for_meeting.assert_awaited_once_with(
            transcript,
            segments=[{"index": 1, "speaker": None, "text": "Ship next week.", "start_ms": None, "end_ms": None}],
            language="fr",
        )
        self.assertEqual(result.language, "fr")
        self.session.commit.assert_awaited_once()

    def test_replace_missing_transcript_does_not_commit(self) -> None:
        self.transcript_repository.get_by_meeting_id.return_value = None

        with self.assertRaises(self.NotFoundError):
            asyncio.run(
                self.service.replace_transcript(
                    str(uuid.uuid4()),
                    segments=[],
                    language="en",
                )
            )

        self.transcript_repository.replace_for_meeting.assert_not_called()
        self.session.commit.assert_not_called()

    def test_invalid_transcript_uuid_raises_validation_error_without_commit(self) -> None:
        with self.assertRaises(self.AppValidationError):
            asyncio.run(self.service.get_transcript("not-a-uuid"))

        self.transcript_repository.get_by_meeting_id.assert_not_called()
        self.session.commit.assert_not_called()

    def test_persistence_errors_propagate_without_commit(self) -> None:
        payload = self.MeetingCreate(
            organization_id=str(uuid.uuid4()),
            created_by=str(uuid.uuid4()),
            title="Planning",
        )
        self.meeting_repository.create.side_effect = RuntimeError("database failed")

        with self.assertRaisesRegex(RuntimeError, "database failed"):
            asyncio.run(self.service.create_meeting(payload))

        self.session.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
