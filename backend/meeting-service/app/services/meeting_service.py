"""Meeting and transcript use cases for meeting-service."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.meeting_repository import MeetingRepository
from app.repositories.transcript_repository import TranscriptRepository
from shared.database.models.meeting import Meeting, MeetingStatus as ORMMeetingStatus
from shared.database.models.transcript import Transcript
from shared.exceptions.common import ConflictError, ForbiddenError, NotFoundError
from shared.exceptions.common import ValidationError as AppValidationError
from shared.schemas.meeting import MeetingCreateRequest, MeetingPublic, MeetingUpdate
from shared.schemas.meeting import MeetingStatus as SchemaMeetingStatus
from shared.schemas.pagination import PaginatedResponse, build_paginated_response
from shared.schemas.transcript import TranscriptBase, TranscriptInDB, TranscriptSegment


class MeetingService:
    """Application use cases for meetings and their transcripts."""

    def __init__(
        self,
        session: AsyncSession,
        meeting_repository: MeetingRepository,
        transcript_repository: TranscriptRepository,
    ) -> None:
        self._session = session
        self._meeting_repository = meeting_repository
        self._transcript_repository = transcript_repository

    async def create_meeting(
        self,
        payload: MeetingCreateRequest,
        authenticated_user_id: UUID,
    ) -> MeetingPublic:
        meeting = Meeting(
            organization_id=self._parse_uuid(payload.organization_id, "organization ID"),
            created_by=authenticated_user_id,
            title=payload.title,
            description=payload.description,
            scheduled_at=payload.scheduled_at,
            participants=payload.participants,
            status=ORMMeetingStatus.PENDING,
        )
        created = await self._meeting_repository.create(meeting)
        await self._session.commit()
        return self._meeting_to_public(created)

    async def get_meeting(
        self,
        meeting_id: str,
        authenticated_user_id: UUID,
    ) -> MeetingPublic:
        meeting = await self._get_owned_meeting(meeting_id, authenticated_user_id)
        return self._meeting_to_public(meeting)

    async def list_meetings(
        self,
        organization_id: str,
        *,
        page: int,
        limit: int,
        offset: int,
    ) -> PaginatedResponse[MeetingPublic]:
        organization_uuid = self._parse_uuid(organization_id, "organization ID")
        meetings = await self._meeting_repository.list_by_organization(
            organization_uuid,
            limit=limit,
            offset=offset,
        )
        total = await self._meeting_repository.count_by_organization(organization_uuid)
        return build_paginated_response(
            [self._meeting_to_public(meeting) for meeting in meetings],
            page=page,
            page_size=limit,
            total=total,
        )

    async def update_meeting_status(
        self,
        meeting_id: str,
        status: SchemaMeetingStatus,
        authenticated_user_id: UUID,
    ) -> MeetingPublic:
        meeting = await self._get_owned_meeting(meeting_id, authenticated_user_id)

        updated = await self._meeting_repository.update_status(
            meeting,
            self._to_orm_status(status),
        )
        await self._session.commit()
        return self._meeting_to_public(updated)

    async def update_meeting(
        self,
        meeting_id: str,
        payload: MeetingUpdate,
        authenticated_user_id: UUID,
    ) -> MeetingPublic:
        meeting = await self._get_owned_meeting(meeting_id, authenticated_user_id)

        for field_name, value in payload.model_dump(exclude_unset=True).items():
            setattr(meeting, field_name, value)

        updated = await self._meeting_repository.update(meeting)
        await self._session.commit()
        return self._meeting_to_public(updated)

    async def create_transcript(
        self,
        payload: TranscriptBase,
        authenticated_user_id: UUID,
    ) -> TranscriptInDB:
        meeting_id = self._parse_uuid(payload.meeting_id, "meeting ID")
        await self._get_owned_meeting(str(meeting_id), authenticated_user_id)

        existing = await self._transcript_repository.get_by_meeting_id(meeting_id)
        if existing is not None:
            raise ConflictError("Transcript already exists.")

        transcript = Transcript(
            meeting_id=meeting_id,
            segments=self._segments_to_dicts(payload.segments),
            language=payload.language,
        )
        created = await self._transcript_repository.create(transcript)
        await self._session.commit()
        return self._transcript_to_in_db(created)

    async def get_transcript(
        self,
        meeting_id: str,
        authenticated_user_id: UUID,
    ) -> TranscriptInDB:
        meeting = await self._get_owned_meeting(meeting_id, authenticated_user_id)
        transcript = await self._transcript_repository.get_by_meeting_id(meeting.id)
        if transcript is None:
            raise NotFoundError("Transcript not found.")
        return self._transcript_to_in_db(transcript)

    async def replace_transcript(
        self,
        meeting_id: str,
        *,
        segments: list[TranscriptSegment],
        language: str | None,
        authenticated_user_id: UUID,
    ) -> TranscriptInDB:
        meeting = await self._get_owned_meeting(meeting_id, authenticated_user_id)
        transcript = await self._transcript_repository.get_by_meeting_id(meeting.id)
        if transcript is None:
            raise NotFoundError("Transcript not found.")

        updated = await self._transcript_repository.replace_for_meeting(
            transcript,
            segments=self._segments_to_dicts(segments),
            language=language,
        )
        await self._session.commit()
        return self._transcript_to_in_db(updated)

    @staticmethod
    def _parse_uuid(value: str, field_name: str) -> UUID:
        try:
            return UUID(value)
        except ValueError as error:
            raise AppValidationError(f"Invalid {field_name}.") from error

    async def _get_owned_meeting(
        self,
        meeting_id: str,
        authenticated_user_id: UUID,
    ) -> Meeting:
        meeting = await self._meeting_repository.get_by_id(
            self._parse_uuid(meeting_id, "meeting ID")
        )
        if meeting is None:
            raise NotFoundError("Meeting not found.")
        if meeting.created_by != authenticated_user_id:
            raise ForbiddenError()
        return meeting

    @staticmethod
    def _to_orm_status(status: SchemaMeetingStatus) -> ORMMeetingStatus:
        try:
            return ORMMeetingStatus(status.value)
        except ValueError as error:
            raise AppValidationError("Invalid meeting status.") from error

    @staticmethod
    def _meeting_to_public(meeting: Meeting) -> MeetingPublic:
        return MeetingPublic(
            id=str(meeting.id),
            title=meeting.title,
            description=meeting.description,
            scheduled_at=meeting.scheduled_at,
            participants=meeting.participants,
            status=SchemaMeetingStatus(meeting.status.value),
            created_at=meeting.created_at,
            updated_at=meeting.updated_at,
        )

    @staticmethod
    def _segments_to_dicts(
        segments: list[TranscriptSegment],
    ) -> list[dict[str, Any]]:
        return [segment.model_dump() for segment in segments]

    @classmethod
    def _transcript_to_in_db(cls, transcript: Transcript) -> TranscriptInDB:
        return TranscriptInDB(
            id=str(transcript.id),
            meeting_id=str(transcript.meeting_id),
            segments=transcript.segments,
            language=transcript.language or "en",
            created_at=transcript.created_at,
            updated_at=transcript.updated_at,
        )
