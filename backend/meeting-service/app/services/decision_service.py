"""Domain use cases for meeting decisions."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.decision_repository import DecisionRepository
from app.services.meeting_service import MeetingService
from shared.database.models.decision import Decision
from shared.exceptions.common import NotFoundError
from shared.exceptions.common import ValidationError as AppValidationError
from shared.schemas.decision import DecisionBase, DecisionInDB


class DecisionService:
    """Coordinate meeting ownership and persisted decision records."""

    def __init__(
        self,
        session: AsyncSession,
        decision_repository: DecisionRepository,
        meeting_service: MeetingService,
    ) -> None:
        self._session = session
        self._decision_repository = decision_repository
        self._meeting_service = meeting_service

    async def create_decision(
        self,
        payload: DecisionBase,
        authenticated_user_id: UUID,
    ) -> DecisionInDB:
        meeting = await self._meeting_service.require_owned_meeting(
            payload.meeting_id, authenticated_user_id
        )
        decision = Decision(
            meeting_id=meeting.id,
            statement=payload.statement,
            context=payload.context,
            participants=payload.participants,
        )
        created = await self._decision_repository.create(decision)
        await self._session.commit()
        return self._to_in_db(created)

    async def get_decision(
        self,
        decision_id: str,
        authenticated_user_id: UUID,
    ) -> DecisionInDB:
        decision = await self._decision_repository.get_by_id(
            self._parse_uuid(decision_id, "decision ID")
        )
        if decision is None:
            raise NotFoundError("Decision not found.")
        await self._meeting_service.require_owned_meeting(
            str(decision.meeting_id), authenticated_user_id
        )
        return self._to_in_db(decision)

    async def list_decisions(
        self,
        meeting_id: str,
        authenticated_user_id: UUID,
    ) -> list[DecisionInDB]:
        meeting = await self._meeting_service.require_owned_meeting(
            meeting_id, authenticated_user_id
        )
        decisions = await self._decision_repository.list_by_meeting_id(meeting.id)
        return [self._to_in_db(decision) for decision in decisions]

    @staticmethod
    def _parse_uuid(value: str, field_name: str) -> UUID:
        try:
            return UUID(value)
        except (TypeError, ValueError) as error:
            raise AppValidationError(f"Invalid {field_name}.") from error

    @staticmethod
    def _to_in_db(decision: Decision) -> DecisionInDB:
        return DecisionInDB(
            id=str(decision.id),
            meeting_id=str(decision.meeting_id),
            statement=decision.statement,
            context=decision.context,
            participants=decision.participants,
            created_at=decision.created_at,
        )
