"""
Purpose: PostgreSQL data access for meetings.
Future responsibilities: CRUD via SQLAlchemy, queries by org/user, status updates.
Service ownership: meeting-service.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.models.meeting import Meeting, MeetingStatus
from shared.database.models.processing_job import ProcessingJobRecord


class MeetingRepository:
    """PostgreSQL data access for persisted meetings."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, meeting: Meeting) -> Meeting:
        self._session.add(meeting)
        await self._session.flush()
        return meeting

    async def get_by_id(self, meeting_id: UUID) -> Meeting | None:
        statement = select(Meeting).where(Meeting.id == meeting_id)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def list_by_organization(
        self,
        organization_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> list[Meeting]:
        statement = (
            select(Meeting)
            .where(Meeting.organization_id == organization_id)
            .order_by(Meeting.created_at.desc(), Meeting.id.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def count_by_organization(self, organization_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(Meeting)
            .where(Meeting.organization_id == organization_id)
        )
        result = await self._session.execute(statement)
        return result.scalar_one()

    async def list_by_owner(
        self,
        owner_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> list[tuple[Meeting, str | None]]:
        """List meetings owned by a user with their latest persisted job status."""
        latest_job_status = (
            select(ProcessingJobRecord.status)
            .where(
                ProcessingJobRecord.meeting_id == Meeting.id,
                ProcessingJobRecord.owner_id == owner_id,
            )
            .order_by(ProcessingJobRecord.created_at.desc(), ProcessingJobRecord.job_id.desc())
            .limit(1)
            .scalar_subquery()
        )
        statement = (
            select(Meeting, latest_job_status.label("processing_status"))
            .where(Meeting.created_by == owner_id)
            .order_by(Meeting.created_at.desc(), Meeting.id.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return [(row[0], row[1]) for row in result.all()]

    async def count_by_owner(self, owner_id: UUID) -> int:
        statement = select(func.count()).select_from(Meeting).where(Meeting.created_by == owner_id)
        result = await self._session.execute(statement)
        return result.scalar_one()

    async def update(self, meeting: Meeting) -> Meeting:
        await self._session.flush()
        return meeting

    async def update_status(
        self,
        meeting: Meeting,
        status: MeetingStatus,
    ) -> Meeting:
        meeting.status = status
        await self._session.flush()
        return meeting
