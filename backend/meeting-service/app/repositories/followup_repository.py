"""Persistence operations for meeting follow-up drafts."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.models.followup import Followup, FollowupStatus


class FollowupRepository:
    """Database access for follow-up drafts and their persisted status."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, followup: Followup) -> Followup:
        self._session.add(followup)
        await self._session.flush()
        return followup

    async def get_by_id(self, followup_id: UUID) -> Followup | None:
        statement = select(Followup).where(Followup.id == followup_id)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def list_by_meeting_id(
        self,
        meeting_id: UUID,
        *,
        status: FollowupStatus | None = None,
    ) -> list[Followup]:
        statement = select(Followup).where(Followup.meeting_id == meeting_id)
        if status is not None:
            statement = statement.where(Followup.status == status)
        statement = statement.order_by(Followup.created_at.desc(), Followup.id.desc())
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def update(self, followup: Followup) -> Followup:
        self._session.add(followup)
        await self._session.flush()
        return followup
