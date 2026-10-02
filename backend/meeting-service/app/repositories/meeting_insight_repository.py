"""Persistence operations for individual meeting insights."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.models.meeting_insight import MeetingInsight


class MeetingInsightRepository:
    """Database access only; transaction ownership remains with a service."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, insight: MeetingInsight) -> MeetingInsight:
        self._session.add(insight)
        await self._session.flush()
        return insight

    async def get_by_id(self, insight_id: UUID) -> MeetingInsight | None:
        statement = select(MeetingInsight).where(MeetingInsight.id == insight_id)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def list_by_meeting_id(self, meeting_id: UUID) -> list[MeetingInsight]:
        statement = (
            select(MeetingInsight)
            .where(MeetingInsight.meeting_id == meeting_id)
            .order_by(MeetingInsight.created_at.asc(), MeetingInsight.id.asc())
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())


__all__ = ["MeetingInsightRepository"]
