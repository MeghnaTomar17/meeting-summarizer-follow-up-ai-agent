"""Persistence operations for meeting decisions."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.models.decision import Decision


class DecisionRepository:
    """Database access for decisions recorded against meetings."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, decision: Decision) -> Decision:
        self._session.add(decision)
        await self._session.flush()
        return decision

    async def get_by_id(self, decision_id: UUID) -> Decision | None:
        statement = select(Decision).where(Decision.id == decision_id)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def list_by_meeting_id(self, meeting_id: UUID) -> list[Decision]:
        statement = (
            select(Decision)
            .where(Decision.meeting_id == meeting_id)
            .order_by(Decision.created_at.asc(), Decision.id.asc())
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())
