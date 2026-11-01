"""Meeting and transcript use cases for meeting-service."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from datetime import timezone
from uuid import UUID, uuid4

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.meeting_repository import MeetingRepository
from app.repositories.meeting_insight_repository import MeetingInsightRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.meeting_submission_repository import MeetingSubmissionRepository
from app.services.organization_authorization import OrganizationAuthorization, OrganizationPermission
from app.repositories.transcript_repository import TranscriptRepository
from shared.database.models.meeting import Meeting, MeetingStatus as ORMMeetingStatus
from shared.database.models.transcript import Transcript
from shared.database.models.processing_job import ProcessingJobRecord
from shared.database.models.job_outbox_event import JobOutboxEvent
from shared.exceptions.common import ConflictError, ForbiddenError, NotFoundError
from shared.exceptions.common import ValidationError as AppValidationError
from shared.schemas.meeting import MeetingCollectionItem, MeetingCreateRequest, MeetingPublic, MeetingUpdate
from shared.schemas.meeting import MeetingStatus as SchemaMeetingStatus
from shared.schemas.pagination import PaginatedResponse, build_paginated_response
from shared.schemas.meeting_insight import MeetingInsightInDB
from shared.schemas.organization import PersonalOrganizationResponse
from shared.schemas.processing_status import MeetingProcessingStatus
from shared.schemas.transcript import TranscriptBase, TranscriptInDB, TranscriptSegment
from shared.schemas.transcript_indexing import TranscriptIndexSource
from shared.schemas.meeting_submission import MeetingSubmissionReceipt, MeetingSubmissionRequest
from shared.schemas.ai_job_envelope import AIProcessingJobEnvelope
from shared.jobs.lifecycle import JobStatus
from shared.schemas.transcript import NormalizedTranscript


class MeetingService:
    """Application use cases for meetings and their transcripts."""

    def __init__(
        self,
        session: AsyncSession,
        meeting_repository: MeetingRepository,
        transcript_repository: TranscriptRepository,
        organization_repository: OrganizationRepository | None = None,
    ) -> None:
        self._session = session
        self._meeting_repository = meeting_repository
        self._transcript_repository = transcript_repository
        self._insight_repository = MeetingInsightRepository(session)
        self._organization_repository = organization_repository or OrganizationRepository(session)
        self._organization_authorization = OrganizationAuthorization(self._organization_repository)
        self._submission_repository = MeetingSubmissionRepository(session)

    async def create_meeting(
        self,
        payload: MeetingCreateRequest,
        authenticated_user_id: UUID,
    ) -> MeetingPublic:
        organization_id = self._parse_uuid(payload.organization_id, "organization ID")
        await self._organization_authorization.require(
            authenticated_user_id,
            organization_id,
            OrganizationPermission.SUBMIT_MEETING,
        )
        meeting = Meeting(
            organization_id=organization_id,
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

    async def submit_meeting(
        self,
        payload: MeetingSubmissionRequest,
        authenticated_user_id: UUID,
        idempotency_key: str,
    ) -> MeetingSubmissionReceipt:
        """Atomically persist meeting input, durable job, idempotency and outbox."""
        if not idempotency_key or idempotency_key != idempotency_key.strip():
            raise AppValidationError("A valid Idempotency-Key header is required.")
        if len(idempotency_key) > 255:
            raise AppValidationError("Idempotency-Key exceeds 255 characters.")

        organization_id = self._parse_uuid(payload.meeting.organization_id, "organization ID")
        request_hash = self._submission_payload_hash(payload, organization_id)
        receipt: MeetingSubmissionReceipt

        async with self._session.begin():
            idempotency_id, existing = await self._submission_repository.claim(
                owner_id=authenticated_user_id,
                operation="meeting_submission",
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise ConflictError("Idempotency-Key was already used with a different submission.")
                await self._organization_authorization.require(
                    authenticated_user_id,
                    organization_id,
                    OrganizationPermission.SUBMIT_MEETING,
                )
                if existing.meeting_id is None or existing.transcript_id is None or existing.job_id is None:
                    raise ConflictError("The original submission receipt is unavailable.")
                receipt = await self._load_submission_receipt(
                    owner_id=authenticated_user_id,
                    organization_id=organization_id,
                    meeting_id=existing.meeting_id,
                    transcript_id=existing.transcript_id,
                    job_id=existing.job_id,
                )
            else:
                await self._organization_authorization.require(
                    authenticated_user_id,
                    organization_id,
                    OrganizationPermission.SUBMIT_MEETING,
                )
                meeting = Meeting(
                    id=uuid4(),
                    organization_id=organization_id,
                    created_by=authenticated_user_id,
                    title=payload.meeting.title,
                    description=payload.meeting.description,
                    scheduled_at=payload.meeting.scheduled_at,
                    participants=payload.meeting.participants,
                    status=ORMMeetingStatus.PENDING,
                )
                meeting = await self._meeting_repository.create(meeting)

                transcript_id = uuid4()
                try:
                    normalized = NormalizedTranscript(
                        meeting_id=meeting.id,
                        transcript_id=transcript_id,
                        language=payload.transcript.language,
                        segments=payload.transcript.segments,
                    )
                except PydanticValidationError as error:
                    raise AppValidationError("Transcript segments are invalid.") from error
                transcript = Transcript(
                    id=transcript_id,
                    meeting_id=meeting.id,
                    revision_number=1,
                    segments=self._segments_to_dicts(normalized.segments),
                    language=normalized.language,
                )
                transcript = await self._transcript_repository.create(transcript)

                job_id = uuid4()
                operations = list(payload.requested_operations)
                job = ProcessingJobRecord(
                    job_id=job_id,
                    meeting_id=meeting.id,
                    transcript_id=transcript.id,
                    owner_id=authenticated_user_id,
                    requested_operations=operations,
                    status=JobStatus.QUEUED.value,
                    attempt_count=0,
                    max_attempts=3,
                )
                envelope = AIProcessingJobEnvelope(
                    job_id=job_id,
                    meeting_id=meeting.id,
                    transcript_id=transcript.id,
                    requested_operations=operations,
                )
                outbox = JobOutboxEvent(
                    id=uuid4(),
                    job_id=job_id,
                    owner_id=authenticated_user_id,
                    event_type="ai.processing.requested.v1",
                    payload=envelope.model_dump(mode="json"),
                    status="pending",
                    attempt_count=0,
                )
                # The two mappers have no ORM relationship configured, so a
                # shared flush does not guarantee dependency ordering. Persist
                # the referenced job first to satisfy the outbox FK; both
                # flushes remain inside the surrounding transaction.
                self._session.add(job)
                await self._session.flush()
                self._session.add(outbox)
                await self._session.flush()
                await self._submission_repository.complete(
                    idempotency_id,
                    owner_id=authenticated_user_id,
                    operation="meeting_submission",
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    meeting_id=meeting.id,
                    transcript_id=transcript.id,
                    job_id=job_id,
                )
                await self._session.flush()
                receipt = MeetingSubmissionReceipt(
                    meeting_id=meeting.id,
                    transcript_id=transcript.id,
                    processing_status=JobStatus.QUEUED,
                )

        # Returning happens only after the context manager committed all five
        # records; no broker call occurs in the request transaction.
        return receipt

    async def _load_submission_receipt(
        self,
        *,
        owner_id: UUID,
        organization_id: UUID,
        meeting_id: UUID,
        transcript_id: UUID,
        job_id: UUID,
    ) -> MeetingSubmissionReceipt:
        meeting = await self._meeting_repository.get_by_id(meeting_id)
        transcript = await self._transcript_repository.get_revision(meeting_id, transcript_id)
        job = await self._session.scalar(
            select(ProcessingJobRecord).where(
                ProcessingJobRecord.job_id == job_id,
                ProcessingJobRecord.meeting_id == meeting_id,
                ProcessingJobRecord.transcript_id == transcript_id,
                ProcessingJobRecord.owner_id == owner_id,
            )
        )
        if (
            meeting is None
            or transcript is None
            or job is None
            or meeting.created_by != owner_id
            or meeting.organization_id != organization_id
        ):
            raise ConflictError("The original submission receipt is unavailable.")
        # This is the original accepted-submission receipt, so its status stays
        # queued even if the durable job has since advanced through its lifecycle.
        return MeetingSubmissionReceipt(
            meeting_id=meeting.id,
            transcript_id=transcript.id,
            processing_status=JobStatus.QUEUED,
        )

    @staticmethod
    def _submission_payload_hash(
        payload: MeetingSubmissionRequest, organization_id: UUID
    ) -> str:
        canonical = payload.model_dump(mode="json")
        canonical["meeting"]["organization_id"] = str(organization_id)
        scheduled_at = payload.meeting.scheduled_at
        if scheduled_at is not None and scheduled_at.tzinfo is not None:
            canonical["meeting"]["scheduled_at"] = scheduled_at.astimezone(timezone.utc).isoformat()
        serialized = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    async def get_personal_organization(
        self, authenticated_user_id: UUID
    ) -> PersonalOrganizationResponse:
        organization = await self._organization_repository.get_personal_for_user(
            authenticated_user_id
        )
        if organization is None:
            raise NotFoundError("Personal organization not found.")
        return PersonalOrganizationResponse(
            id=str(organization.id),
            name=organization.name,
            role="owner",
            created_at=organization.created_at,
        )

    async def get_meeting(
        self,
        meeting_id: str,
        authenticated_user_id: UUID,
    ) -> MeetingPublic:
        meeting = await self.require_owned_meeting(meeting_id, authenticated_user_id)
        return self._meeting_to_public(meeting)

    async def list_meeting_insights(
        self, meeting_id: str, owner_id: UUID, *, page: int, page_size: int
    ) -> PaginatedResponse[MeetingInsightInDB]:
        meeting = await self.require_owned_meeting(meeting_id, owner_id)
        records = await self._insight_repository.list_by_meeting_id(meeting.id)
        items = [
            MeetingInsightInDB(
                id=str(record.id), meeting_id=str(record.meeting_id),
                category=record.category, title=record.title,
                description=record.description, created_at=record.created_at,
            )
            for record in records
        ]
        start = (page - 1) * page_size
        return build_paginated_response(
            items[start : start + page_size], page=page,
            page_size=page_size, total=len(items),
        )

    async def get_processing_status(
        self, meeting_id: str, owner_id: UUID
    ) -> MeetingProcessingStatus:
        meeting = await self.require_owned_meeting(meeting_id, owner_id)
        job = await self._meeting_repository.latest_processing_job(meeting.id, owner_id)
        if job is None:
            return MeetingProcessingStatus(meeting_id=meeting.id)
        return MeetingProcessingStatus(
            meeting_id=meeting.id, status=job.status,
            updated_at=job.updated_at, completed_at=job.completed_at,
        )

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

    async def list_owned_meetings(
        self,
        owner_id: UUID,
        *,
        page: int,
        limit: int,
        offset: int,
    ) -> PaginatedResponse[MeetingCollectionItem]:
        """Return a bounded collection for the authenticated owner only."""
        rows = await self._meeting_repository.list_by_owner(
            owner_id, limit=limit, offset=offset
        )
        total = await self._meeting_repository.count_by_owner(owner_id)
        items = [
            MeetingCollectionItem(
                **self._meeting_to_public(meeting).model_dump(),
                processing_status=processing_status,
            )
            for meeting, processing_status in rows
        ]
        return build_paginated_response(items, page=page, page_size=limit, total=total)

    async def update_meeting_status(
        self,
        meeting_id: str,
        status: SchemaMeetingStatus,
        authenticated_user_id: UUID,
    ) -> MeetingPublic:
        meeting = await self.require_owned_meeting(meeting_id, authenticated_user_id)

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
        meeting = await self.require_owned_meeting(meeting_id, authenticated_user_id)

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
        await self.require_owned_meeting(str(meeting_id), authenticated_user_id)

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
        meeting = await self.require_owned_meeting(meeting_id, authenticated_user_id)
        transcript = await self._transcript_repository.get_by_meeting_id(meeting.id)
        if transcript is None:
            raise NotFoundError("Transcript not found.")
        return self._transcript_to_in_db(transcript)

    async def get_transcript_revision(
        self,
        meeting_id: str,
        transcript_id: UUID,
        authenticated_user_id: UUID,
    ) -> TranscriptInDB:
        """Resolve one immutable transcript revision after the owner check."""
        meeting = await self.require_owned_meeting(meeting_id, authenticated_user_id)
        transcript = await self._transcript_repository.get_revision(
            meeting.id, transcript_id
        )
        if transcript is None:
            raise NotFoundError("Transcript not found.")
        return self._transcript_to_in_db(transcript)

    async def get_transcript_index_source(
        self,
        meeting_id: str,
        authenticated_user_id: UUID,
    ) -> TranscriptIndexSource:
        """Return persisted transcript and authoritative scope after ownership check."""
        meeting = await self.require_owned_meeting(meeting_id, authenticated_user_id)
        transcript = await self._transcript_repository.get_by_meeting_id(meeting.id)
        if transcript is None:
            raise NotFoundError("Transcript not found.")
        return TranscriptIndexSource(
            transcript=self._transcript_to_in_db(transcript),
            organization_id=meeting.organization_id,
        )

    async def replace_transcript(
        self,
        meeting_id: str,
        *,
        segments: list[TranscriptSegment],
        language: str | None,
        authenticated_user_id: UUID,
    ) -> TranscriptInDB:
        meeting = await self.require_owned_meeting(meeting_id, authenticated_user_id)
        transcript = await self._transcript_repository.get_by_meeting_id(meeting.id)
        if transcript is None:
            raise NotFoundError("Transcript not found.")

        revision = await self._transcript_repository.create_revision(
            meeting.id,
            segments=self._segments_to_dicts(segments),
            language=language,
        )
        await self._session.commit()
        return self._transcript_to_in_db(revision)

    @staticmethod
    def _parse_uuid(value: str, field_name: str) -> UUID:
        try:
            return UUID(value)
        except ValueError as error:
            raise AppValidationError(f"Invalid {field_name}.") from error

    async def require_owned_meeting(
        self,
        meeting_id: str,
        authenticated_user_id: UUID,
    ) -> Meeting:
        """Return a meeting only after applying the canonical ownership check."""
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
