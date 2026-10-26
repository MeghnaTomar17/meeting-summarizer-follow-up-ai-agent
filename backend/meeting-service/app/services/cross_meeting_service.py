"""Application orchestration for structured cross-meeting evidence queries."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from app.repositories.cross_meeting_repository import CrossMeetingRepository
from shared.schemas.cross_meeting import (
    CrossMeetingDataQuery,
    CrossMeetingDecisionRecord,
    CrossMeetingInsightRecord,
    CrossMeetingRecord,
    CrossMeetingStructuredData,
    CrossMeetingTaskRecord,
)
from shared.schemas.pagination import build_paginated_response


class CrossMeetingService:
    """Assemble typed record pages without adding search or answer logic."""

    def __init__(
        self,
        repository: CrossMeetingRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def query(
        self, query: CrossMeetingDataQuery, *, owner_id: UUID
    ) -> CrossMeetingStructuredData:
        common = {
            "since": query.since,
            "until": query.until,
            "page": query.page,
            "page_size": query.page_size,
        }
        meetings, meeting_total = await self._repository.list_meetings(owner_id, **common)
        tasks, task_total = await self._repository.list_tasks(
            owner_id,
            **common,
            task_filter=query.task_filter,
            as_of=self._clock(),
        )
        decisions, decision_total = await self._repository.list_decisions(owner_id, **common)
        insights, insight_total = await self._repository.list_insights(owner_id, **common)

        return CrossMeetingStructuredData(
            meetings=build_paginated_response(
                [CrossMeetingRecord(
                    id=row.id, title=row.title, description=row.description,
                    scheduled_at=row.scheduled_at, created_at=row.created_at,
                ) for row in meetings],
                page=query.page, page_size=query.page_size, total=meeting_total,
            ),
            tasks=build_paginated_response(
                [CrossMeetingTaskRecord(
                    id=row.id, meeting_id=row.meeting_id, title=row.title,
                    description=row.description, status=row.status,
                    due_at=row.due_at, created_at=row.created_at,
                ) for row in tasks],
                page=query.page, page_size=query.page_size, total=task_total,
            ),
            decisions=build_paginated_response(
                [CrossMeetingDecisionRecord(
                    id=row.id, meeting_id=row.meeting_id, statement=row.statement,
                    context=row.context, participants=row.participants,
                    created_at=row.created_at,
                ) for row in decisions],
                page=query.page, page_size=query.page_size, total=decision_total,
            ),
            insights=build_paginated_response(
                [CrossMeetingInsightRecord(
                    id=row.id, meeting_id=row.meeting_id, category=row.category,
                    title=row.title, description=row.description,
                    created_at=row.created_at,
                ) for row in insights],
                page=query.page, page_size=query.page_size, total=insight_total,
            ),
        )


__all__ = ["CrossMeetingService"]
