"""Persistence operations for versioned meeting summaries."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.models.summary import Summary


class SummaryRepository:
    """Database access for meeting summary versions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, summary: Summary) -> Summary:
        self._session.add(summary)
        await self._session.flush()
        return summary

    async def get_by_id(self, summary_id: UUID) -> Summary | None:
        statement = select(Summary).where(Summary.id == summary_id)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def list_by_meeting_id(self, meeting_id: UUID) -> list[Summary]:
        statement = (
            select(Summary)
            .where(Summary.meeting_id == meeting_id)
            .order_by(Summary.version.asc(), Summary.id.asc())
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def get_latest_by_meeting_id(self, meeting_id: UUID) -> Summary | None:
        statement = (
            select(Summary)
            .where(Summary.meeting_id == meeting_id)
            .order_by(Summary.version.desc())
            .limit(1)
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()
