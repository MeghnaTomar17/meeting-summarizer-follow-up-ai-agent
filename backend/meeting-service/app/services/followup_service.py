"""Domain use cases for persisted meeting follow-up drafts."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.followup_repository import FollowupRepository
from app.services.meeting_service import MeetingService
from shared.database.models.followup import Followup, FollowupStatus as ORMFollowupStatus
from shared.exceptions.common import NotFoundError
from shared.exceptions.common import ValidationError as AppValidationError
from shared.schemas.followup import FollowupBase, FollowupInDB
from shared.schemas.followup import FollowupStatus as SchemaFollowupStatus
from shared.schemas.followup import FollowupUpdate


class FollowUpService:
    """Coordinate meeting ownership and persisted follow-up draft data."""

    def __init__(
        self,
        session: AsyncSession,
        followup_repository: FollowupRepository,
        meeting_service: MeetingService,
    ) -> None:
        self._session = session
        self._followup_repository = followup_repository
        self._meeting_service = meeting_service

    async def create_followup(
        self,
        payload: FollowupBase,
        authenticated_user_id: UUID,
    ) -> FollowupInDB:
        meeting = await self._meeting_service.require_owned_meeting(
            payload.meeting_id, authenticated_user_id
        )
        followup = Followup(
            meeting_id=meeting.id,
            subject=payload.subject,
            body_html=payload.body_html,
            recipients=[str(recipient) for recipient in payload.recipients],
            status=ORMFollowupStatus.DRAFT,
        )
        created = await self._followup_repository.create(followup)
        await self._session.commit()
        return self._to_in_db(created)

    async def get_followup(
        self,
        followup_id: str,
        authenticated_user_id: UUID,
    ) -> FollowupInDB:
        followup = await self._followup_repository.get_by_id(
            self._parse_uuid(followup_id, "follow-up ID")
        )
        if followup is None:
            raise NotFoundError("Follow-up not found.")
        await self._meeting_service.require_owned_meeting(
            str(followup.meeting_id), authenticated_user_id
        )
        return self._to_in_db(followup)

    async def list_followups(
        self,
        meeting_id: str,
        authenticated_user_id: UUID,
        *,
        status: SchemaFollowupStatus | str | None = None,
    ) -> list[FollowupInDB]:
        meeting = await self._meeting_service.require_owned_meeting(
            meeting_id, authenticated_user_id
        )
        orm_status = self._to_orm_status(status) if status is not None else None
        followups = await self._followup_repository.list_by_meeting_id(
            meeting.id, status=orm_status
        )
        return [self._to_in_db(followup) for followup in followups]

    async def update_followup(
        self,
        followup_id: str,
        payload: FollowupUpdate,
        authenticated_user_id: UUID,
    ) -> FollowupInDB:
        followup = await self._followup_repository.get_by_id(
            self._parse_uuid(followup_id, "follow-up ID")
        )
        if followup is None:
            raise NotFoundError("Follow-up not found.")
        await self._meeting_service.require_owned_meeting(
            str(followup.meeting_id), authenticated_user_id
        )

        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            return self._to_in_db(followup)
        if "recipients" in changes:
            changes["recipients"] = [str(item) for item in changes["recipients"]]
        if "status" in changes:
            changes["status"] = self._to_orm_status(changes["status"])
        for field_name, value in changes.items():
            setattr(followup, field_name, value)

        updated = await self._followup_repository.update(followup)
        await self._session.commit()
        return self._to_in_db(updated)

    @staticmethod
    def _parse_uuid(value: str, field_name: str) -> UUID:
        try:
            return UUID(value)
        except (TypeError, ValueError) as error:
            raise AppValidationError(f"Invalid {field_name}.") from error

    @staticmethod
    def _to_orm_status(
        status: SchemaFollowupStatus | str,
    ) -> ORMFollowupStatus:
        value = status.value if isinstance(status, SchemaFollowupStatus) else status
        try:
            return ORMFollowupStatus(value)
        except (TypeError, ValueError) as error:
            raise AppValidationError("Invalid follow-up status.") from error

    @staticmethod
    def _to_in_db(followup: Followup) -> FollowupInDB:
        return FollowupInDB(
            id=str(followup.id),
            meeting_id=str(followup.meeting_id),
            subject=followup.subject,
            body_html=followup.body_html,
            recipients=followup.recipients,
            status=SchemaFollowupStatus(followup.status.value),
            scheduled_at=followup.scheduled_at,
            sent_at=followup.sent_at,
            created_at=followup.created_at,
        )
