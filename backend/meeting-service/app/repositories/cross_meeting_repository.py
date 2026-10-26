"""Owner-scoped structured queries used by cross-meeting intelligence."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.models.decision import Decision
from shared.database.models.meeting import Meeting
from shared.database.models.meeting_insight import MeetingInsight
from shared.database.models.task import Task, TaskStatus
from shared.schemas.cross_meeting import StructuredTaskFilter


class CrossMeetingRepository:
    """Query structured evidence only through meetings owned by the caller."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_meetings(
        self, owner_id: UUID, *, since: datetime | None, until: datetime | None,
        page: int, page_size: int,
    ) -> tuple[list[Meeting], int]:
        return await self._list_page(
            Meeting, owner_id, timestamp=Meeting.scheduled_at,
            since=since, until=until, page=page, page_size=page_size,
        )

    async def list_tasks(
        self, owner_id: UUID, *, since: datetime | None, until: datetime | None,
        task_filter: StructuredTaskFilter, as_of: datetime,
        page: int, page_size: int,
    ) -> tuple[list[Task], int]:
        filters: list[Any] = []
        if task_filter == StructuredTaskFilter.UNRESOLVED:
            filters.append(Task.status.in_((TaskStatus.OPEN, TaskStatus.IN_PROGRESS)))
        elif task_filter == StructuredTaskFilter.OVERDUE:
            filters.extend((
                Task.due_at.is_not(None),
                Task.due_at < as_of,
                Task.status.notin_((TaskStatus.DONE, TaskStatus.CANCELLED)),
            ))
        return await self._list_page(
            Task, owner_id, timestamp=Task.created_at, since=since, until=until,
            page=page, page_size=page_size, filters=filters,
        )

    async def list_decisions(
        self, owner_id: UUID, *, since: datetime | None, until: datetime | None,
        page: int, page_size: int,
    ) -> tuple[list[Decision], int]:
        return await self._list_page(
            Decision, owner_id, timestamp=Decision.created_at, since=since,
            until=until, page=page, page_size=page_size,
        )

    async def list_insights(
        self, owner_id: UUID, *, since: datetime | None, until: datetime | None,
        page: int, page_size: int,
    ) -> tuple[list[MeetingInsight], int]:
        return await self._list_page(
            MeetingInsight, owner_id, timestamp=MeetingInsight.created_at,
            since=since, until=until, page=page, page_size=page_size,
        )

    async def _list_page(
        self,
        model: Any,
        owner_id: UUID,
        *,
        timestamp: Any,
        since: datetime | None,
        until: datetime | None,
        page: int,
        page_size: int,
        filters: list[Any] | None = None,
    ) -> tuple[list[Any], int]:
        """Use one parent join and distinct IDs to keep evidence rows unique."""
        predicates = [Meeting.created_by == owner_id]
        if model is not Meeting:
            predicates.append(model.meeting_id == Meeting.id)
        if since is not None:
            predicates.append(timestamp >= since)
        if until is not None:
            predicates.append(timestamp < until)
        predicates.extend(filters or [])

        source = select(model).select_from(model)
        count_source = select(func.count(func.distinct(model.id))).select_from(model)
        if model is not Meeting:
            source = source.join(Meeting, model.meeting_id == Meeting.id)
            count_source = count_source.join(Meeting, model.meeting_id == Meeting.id)
        source = source.where(*predicates).distinct()
        count_source = count_source.where(*predicates)

        if model is Meeting:
            source = source.order_by(
                Meeting.scheduled_at.desc().nullslast(),
                Meeting.created_at.desc(), Meeting.id.desc(),
            )
        else:
            source = source.order_by(timestamp.desc(), model.id.desc())
        source = source.offset((page - 1) * page_size).limit(page_size)

        rows_result = await self._session.execute(source)
        count_result = await self._session.execute(count_source)
        return list(rows_result.scalars().all()), int(count_result.scalar_one())


__all__ = ["CrossMeetingRepository"]
