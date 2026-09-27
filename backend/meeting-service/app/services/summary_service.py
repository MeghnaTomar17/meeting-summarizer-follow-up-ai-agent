"""Domain use cases for persisted meeting summaries."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.summary_repository import SummaryRepository
from app.services.meeting_service import MeetingService
from shared.database.models.summary import Summary
from shared.exceptions.common import ConflictError, NotFoundError
from shared.exceptions.common import ValidationError as AppValidationError
from shared.schemas.summary import SummaryBase, SummaryInDB


class SummaryService:
    """Coordinate ownership checks, summary persistence, and transactions."""

    def __init__(
        self,
        session: AsyncSession,
        summary_repository: SummaryRepository,
        meeting_service: MeetingService,
    ) -> None:
        self._session = session
        self._summary_repository = summary_repository
        self._meeting_service = meeting_service

    async def create_summary(
        self,
        payload: SummaryBase,
        authenticated_user_id: UUID,
        *,
        version: int = 1,
    ) -> SummaryInDB:
        """Persist the requested version; version assignment is not automatic."""
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise AppValidationError("Summary version must be a positive integer.")

        meeting = await self._meeting_service.require_owned_meeting(
            payload.meeting_id, authenticated_user_id
        )
        summary = Summary(
            meeting_id=meeting.id,
            content=payload.content,
            key_topics=payload.key_topics,
            model_provider=payload.model_provider,
            model_name=payload.model_name,
            version=version,
        )
        try:
            created = await self._summary_repository.create(summary)
            await self._session.commit()
        except IntegrityError as error:
            if self._is_version_conflict(error):
                raise ConflictError("Summary version already exists.") from error
            raise
        return self._to_in_db(created)

    async def get_summary(
        self,
        summary_id: str,
        authenticated_user_id: UUID,
    ) -> SummaryInDB:
        summary = await self._summary_repository.get_by_id(
            self._parse_uuid(summary_id, "summary ID")
        )
        if summary is None:
            raise NotFoundError("Summary not found.")
        await self._meeting_service.require_owned_meeting(
            str(summary.meeting_id), authenticated_user_id
        )
        return self._to_in_db(summary)

    async def list_summaries(
        self,
        meeting_id: str,
        authenticated_user_id: UUID,
    ) -> list[SummaryInDB]:
        meeting = await self._meeting_service.require_owned_meeting(
            meeting_id, authenticated_user_id
        )
        summaries = await self._summary_repository.list_by_meeting_id(meeting.id)
        return [self._to_in_db(summary) for summary in summaries]

    async def get_latest_summary(
        self,
        meeting_id: str,
        authenticated_user_id: UUID,
    ) -> SummaryInDB:
        meeting = await self._meeting_service.require_owned_meeting(
            meeting_id, authenticated_user_id
        )
        summary = await self._summary_repository.get_latest_by_meeting_id(meeting.id)
        if summary is None:
            raise NotFoundError("Summary not found.")
        return self._to_in_db(summary)

    @staticmethod
    def _parse_uuid(value: str, field_name: str) -> UUID:
        try:
            return UUID(value)
        except (TypeError, ValueError) as error:
            raise AppValidationError(f"Invalid {field_name}.") from error

    @staticmethod
    def _is_version_conflict(error: IntegrityError) -> bool:
        expected = "uq_summaries_meeting_version"
        pending = [error.orig]
        seen: set[int] = set()
        while pending:
            cause = pending.pop()
            if cause is None or id(cause) in seen:
                continue
            seen.add(id(cause))
            if getattr(cause, "constraint_name", None) == expected:
                return True
            diagnostic = getattr(cause, "diag", None)
            if getattr(diagnostic, "constraint_name", None) == expected:
                return True
            if expected in str(cause):
                return True
            pending.extend(
                (
                    getattr(cause, "__cause__", None),
                    getattr(cause, "__context__", None),
                )
            )
        return False

    @staticmethod
    def _to_in_db(summary: Summary) -> SummaryInDB:
        return SummaryInDB(
            id=str(summary.id),
            meeting_id=str(summary.meeting_id),
            content=summary.content,
            key_topics=summary.key_topics,
            model_provider=summary.model_provider,
            model_name=summary.model_name,
            version=summary.version,
            created_at=summary.created_at,
        )
