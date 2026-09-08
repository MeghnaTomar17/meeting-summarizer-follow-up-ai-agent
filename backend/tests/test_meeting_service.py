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

from pydantic import ValidationError as PydanticValidationError
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
        from shared.exceptions.common import ConflictError, ForbiddenError, NotFoundError
        from shared.exceptions.common import ValidationError as AppValidationError
        from shared.schemas.meeting import MeetingCreateRequest, MeetingStatus, MeetingUpdate
        from shared.schemas.transcript import TranscriptBase, TranscriptSegment

        self.Meeting = Meeting
        self.ORMMeetingStatus = ORMMeetingStatus
        self.Transcript = Transcript
        self.ConflictError = ConflictError
        self.ForbiddenError = ForbiddenError
        self.NotFoundError = NotFoundError
        self.AppValidationError = AppValidationError
        self.MeetingCreateRequest = MeetingCreateRequest
        self.MeetingStatus = MeetingStatus
        self.MeetingUpdate = MeetingUpdate
        self.TranscriptBase = TranscriptBase
        self.TranscriptSegment = TranscriptSegment

        self.session = MagicMock(spec=AsyncSession)
        self.session.commit = AsyncMock()
        self.meeting_repository = MagicMock(spec=MeetingRepository)
        self.transcript_repository = MagicMock(spec=TranscriptRepository)
        self.meeting_repository.create = AsyncMock()
        self.meeting_repository.get_by_id = AsyncMock()
        self.meeting_repository.list_by_organization = AsyncMock()
        self.meeting_repository.count_by_organization = AsyncMock()
        self.meeting_repository.update = AsyncMock()
        self.meeting_repository.update_status = AsyncMock()
        self.transcript_repository.create = AsyncMock()
        self.transcript_repository.get_by_meeting_id = AsyncMock()
        self.transcript_repository.replace_for_meeting = AsyncMock()
        self.service = self.MeetingService(
            self.session,
            self.meeting_repository,
            self.transcript_repository,
        )
        self.user_id = uuid.uuid4()

    def _meeting(self) -> object:
        now = datetime.now(timezone.utc)
        return self.Meeting(
            id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            created_by=self.user_id,
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
        created = self._meeting()
        self.meeting_repository.create.return_value = created
        payload = self.MeetingCreateRequest(
            organization_id=str(organization_id),
            title="Planning",
            description="Q4 planning",
            participants=["alice@example.com"],
        )

        result = asyncio.run(self.service.create_meeting(payload, self.user_id))

        submitted = self.meeting_repository.create.await_args.args[0]
        self.assertEqual(submitted.organization_id, organization_id)
        self.assertEqual(submitted.created_by, self.user_id)
        self.assertEqual(submitted.status, self.ORMMeetingStatus.PENDING)
        self.assertEqual(submitted.participants, ["alice@example.com"])
        self.assertEqual(result.id, str(created.id))
        self.session.commit.assert_awaited_once()

    def test_invalid_meeting_uuid_raises_validation_error_without_commit(self) -> None:
        payload = self.MeetingCreateRequest(
            organization_id="not-a-uuid",
            title="Planning",
        )

        with self.assertRaises(self.AppValidationError):
            asyncio.run(self.service.create_meeting(payload, self.user_id))

        self.meeting_repository.create.assert_not_called()
        self.session.commit.assert_not_called()

    def test_get_meeting_returns_public_dto_without_commit(self) -> None:
        meeting = self._meeting()
        self.meeting_repository.get_by_id.return_value = meeting

        result = asyncio.run(self.service.get_meeting(str(meeting.id), self.user_id))

        self.assertEqual(result.id, str(meeting.id))
        self.assertEqual(result.status, self.MeetingStatus.PENDING)
        self.meeting_repository.get_by_id.assert_awaited_once_with(meeting.id)
        self.session.commit.assert_not_called()

    def test_get_missing_meeting_raises_not_found_without_commit(self) -> None:
        self.meeting_repository.get_by_id.return_value = None

        with self.assertRaises(self.NotFoundError):
            asyncio.run(self.service.get_meeting(str(uuid.uuid4()), self.user_id))

        self.session.commit.assert_not_called()

    def test_list_meetings_builds_paginated_response_without_commit(self) -> None:
        organization_id = uuid.uuid4()
        meeting = self._meeting()
        self.meeting_repository.list_by_organization.return_value = [meeting]
        self.meeting_repository.count_by_organization.return_value = 41

        result = asyncio.run(
            self.service.list_meetings(
                str(organization_id),
                page=3,
                limit=20,
                offset=40,
            )
        )

        self.assertEqual([item.id for item in result.items], [str(meeting.id)])
        self.assertEqual(result.pagination.page, 3)
        self.assertEqual(result.pagination.page_size, 20)
        self.assertEqual(result.pagination.total, 41)
        self.assertEqual(result.pagination.total_pages, 3)
        self.meeting_repository.list_by_organization.assert_awaited_once_with(
            organization_id,
            limit=20,
            offset=40,
        )
        self.meeting_repository.count_by_organization.assert_awaited_once_with(
            organization_id
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
                self.user_id,
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
                    self.user_id,
                )
            )

        self.meeting_repository.update_status.assert_not_called()
        self.session.commit.assert_not_called()

    def test_update_meeting_applies_only_supplied_fields_and_commits_once(self) -> None:
        meeting = self._meeting()
        meeting.description = "Existing description"
        meeting.scheduled_at = datetime(2026, 9, 7, tzinfo=timezone.utc)
        meeting.participants = ["alice@example.com"]
        self.meeting_repository.get_by_id.return_value = meeting
        self.meeting_repository.update.return_value = meeting
        payload = self.MeetingUpdate(
            title="Updated weekly sync",
            participants=["bob@example.com"],
        )

        result = asyncio.run(self.service.update_meeting(str(meeting.id), payload, self.user_id))

        self.assertEqual(meeting.title, "Updated weekly sync")
        self.assertEqual(meeting.participants, ["bob@example.com"])
        self.assertEqual(meeting.description, "Existing description")
        self.assertEqual(
            meeting.scheduled_at,
            datetime(2026, 9, 7, tzinfo=timezone.utc),
        )
        self.meeting_repository.get_by_id.assert_awaited_once_with(meeting.id)
        self.meeting_repository.update.assert_awaited_once_with(meeting)
        self.session.commit.assert_awaited_once()
        self.session.rollback.assert_not_called()
        self.assertEqual(result.id, str(meeting.id))
        self.assertEqual(result.title, "Updated weekly sync")
        self.assertEqual(result.description, "Existing description")

    def test_meeting_update_schema_accepts_non_nullable_mutable_values(self) -> None:
        payload = self.MeetingUpdate(
            title="Updated weekly sync",
            participants=["alice@example.com"],
        )

        self.assertEqual(payload.title, "Updated weekly sync")
        self.assertEqual(payload.participants, ["alice@example.com"])

    def test_meeting_update_schema_allows_clearing_nullable_fields(self) -> None:
        payload = self.MeetingUpdate(description=None, scheduled_at=None)

        self.assertEqual(
            payload.model_dump(exclude_unset=True),
            {"description": None, "scheduled_at": None},
        )

    def test_meeting_update_schema_rejects_null_non_nullable_fields(self) -> None:
        with self.assertRaises(PydanticValidationError):
            self.MeetingUpdate(title=None)

        with self.assertRaises(PydanticValidationError):
            self.MeetingUpdate(participants=None)

    def test_update_meeting_missing_entity_does_not_commit(self) -> None:
        self.meeting_repository.get_by_id.return_value = None

        with self.assertRaisesRegex(self.NotFoundError, "Meeting not found."):
            asyncio.run(
                self.service.update_meeting(
                    str(uuid.uuid4()),
                    self.MeetingUpdate(title="Updated weekly sync"),
                    self.user_id,
                )
            )

        self.meeting_repository.update.assert_not_called()
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()

    def test_update_meeting_invalid_uuid_does_not_query_or_commit(self) -> None:
        with self.assertRaises(self.AppValidationError):
            asyncio.run(
                self.service.update_meeting(
                    "not-a-uuid",
                    self.MeetingUpdate(title="Updated weekly sync"),
                    self.user_id,
                )
            )

        self.meeting_repository.get_by_id.assert_not_called()
        self.meeting_repository.update.assert_not_called()
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()

    def test_update_meeting_persistence_error_propagates_without_commit(self) -> None:
        meeting = self._meeting()
        self.meeting_repository.get_by_id.return_value = meeting
        self.meeting_repository.update.side_effect = RuntimeError("database failed")

        with self.assertRaisesRegex(RuntimeError, "database failed"):
            asyncio.run(
                self.service.update_meeting(
                    str(meeting.id),
                    self.MeetingUpdate(title="Updated weekly sync"),
                    self.user_id,
                )
            )

        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()

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

        result = asyncio.run(self.service.create_transcript(payload, self.user_id))

        submitted = self.transcript_repository.create.await_args.args[0]
        self.assertEqual(submitted.meeting_id, meeting.id)
        self.assertEqual(submitted.segments, [{"index": 0, "speaker": None, "text": "Plan the release.", "start_ms": None, "end_ms": None}])
        self.assertEqual(result.id, str(created.id))
        self.session.commit.assert_awaited_once()

    def test_create_transcript_missing_meeting_does_not_commit(self) -> None:
        self.meeting_repository.get_by_id.return_value = None
        payload = self.TranscriptBase(meeting_id=str(uuid.uuid4()))

        with self.assertRaises(self.NotFoundError):
            asyncio.run(self.service.create_transcript(payload, self.user_id))

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
            asyncio.run(self.service.create_transcript(payload, self.user_id))

        self.transcript_repository.create.assert_not_called()
        self.session.commit.assert_not_called()

    def test_get_transcript_and_missing_transcript_do_not_commit(self) -> None:
        meeting = self._meeting()
        transcript = self._transcript(meeting.id)
        self.meeting_repository.get_by_id.return_value = meeting
        self.transcript_repository.get_by_meeting_id.return_value = transcript

        result = asyncio.run(self.service.get_transcript(str(transcript.meeting_id), self.user_id))
        self.assertEqual(result.id, str(transcript.id))
        self.session.commit.assert_not_called()

        self.transcript_repository.get_by_meeting_id.return_value = None
        with self.assertRaises(self.NotFoundError):
            asyncio.run(self.service.get_transcript(str(meeting.id), self.user_id))
        self.session.commit.assert_not_called()

    def test_replace_transcript_maps_segments_and_commits_once(self) -> None:
        meeting = self._meeting()
        transcript = self._transcript(meeting.id)
        updated = self._transcript(transcript.meeting_id)
        updated.segments = [{"index": 1, "text": "Ship next week."}]
        updated.language = "fr"
        self.transcript_repository.get_by_meeting_id.return_value = transcript
        self.meeting_repository.get_by_id.return_value = meeting
        self.transcript_repository.replace_for_meeting.return_value = updated
        segments = [self.TranscriptSegment(index=1, text="Ship next week.")]

        result = asyncio.run(
            self.service.replace_transcript(
                str(transcript.meeting_id),
                segments=segments,
                language="fr",
                authenticated_user_id=self.user_id,
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
        meeting = self._meeting()
        self.meeting_repository.get_by_id.return_value = meeting
        self.transcript_repository.get_by_meeting_id.return_value = None

        with self.assertRaises(self.NotFoundError):
            asyncio.run(
                self.service.replace_transcript(
                    str(meeting.id),
                    segments=[],
                    language="en",
                    authenticated_user_id=self.user_id,
                )
            )

        self.transcript_repository.replace_for_meeting.assert_not_called()
        self.session.commit.assert_not_called()

    def test_invalid_transcript_uuid_raises_validation_error_without_commit(self) -> None:
        with self.assertRaises(self.AppValidationError):
            asyncio.run(self.service.get_transcript("not-a-uuid", self.user_id))

        self.transcript_repository.get_by_meeting_id.assert_not_called()
        self.session.commit.assert_not_called()

    def test_persistence_errors_propagate_without_commit(self) -> None:
        payload = self.MeetingCreateRequest(
            organization_id=str(uuid.uuid4()),
            title="Planning",
        )
        self.meeting_repository.create.side_effect = RuntimeError("database failed")

        with self.assertRaisesRegex(RuntimeError, "database failed"):
            asyncio.run(self.service.create_meeting(payload, self.user_id))

        self.session.commit.assert_not_called()

    def test_non_owner_is_forbidden_without_commit(self) -> None:
        meeting = self._meeting()
        self.meeting_repository.get_by_id.return_value = meeting

        with self.assertRaises(self.ForbiddenError):
            asyncio.run(self.service.get_meeting(str(meeting.id), uuid.uuid4()))

        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()

    def test_non_owner_cannot_mutate_meeting_or_transcript(self) -> None:
        meeting = self._meeting()
        transcript = self._transcript(meeting.id)
        intruder_id = uuid.uuid4()
        self.meeting_repository.get_by_id.return_value = meeting

        for operation in (
            lambda: self.service.update_meeting(
                str(meeting.id), self.MeetingUpdate(title="Not allowed"), intruder_id
            ),
            lambda: self.service.update_meeting_status(
                str(meeting.id), self.MeetingStatus.READY, intruder_id
            ),
            lambda: self.service.create_transcript(
                self.TranscriptBase(meeting_id=str(meeting.id)), intruder_id
            ),
            lambda: self.service.get_transcript(str(meeting.id), intruder_id),
            lambda: self.service.replace_transcript(
                str(meeting.id), segments=[], language="en", authenticated_user_id=intruder_id
            ),
        ):
            with self.subTest(operation=operation), self.assertRaises(self.ForbiddenError):
                asyncio.run(operation())

        self.meeting_repository.update.assert_not_called()
        self.meeting_repository.update_status.assert_not_called()
        self.transcript_repository.create.assert_not_called()
        self.transcript_repository.replace_for_meeting.assert_not_called()
        self.session.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
