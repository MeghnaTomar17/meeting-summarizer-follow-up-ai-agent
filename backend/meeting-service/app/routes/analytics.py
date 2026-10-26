"""Authenticated internal dashboard analytics endpoint."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_authenticated_user_id
from app.repositories.analytics_repository import AnalyticsRepository
from app.services.analytics_service import (
    AnalyticsService,
)
from shared.database.session import get_db_session
from shared.schemas.analytics import (
    DEFAULT_ANALYTICS_WEEKS,
    MAX_ANALYTICS_WEEKS,
    AnalyticsOverviewResponse,
    AnalyticsTrendsResponse,
    RecurringBlockersResponse,
    DEFAULT_TOPICS_PER_WEEK,
    DEFAULT_SPEAKER_MEETING_LIMIT,
    MAX_TOPICS_PER_WEEK,
    MAX_SPEAKER_MEETING_LIMIT,
    SpeakerParticipationResponse,
    TaskCompletionTrendsResponse,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


async def get_analytics_service(
    session: AsyncSession = Depends(get_db_session),
) -> AnalyticsService:
    return AnalyticsService(AnalyticsRepository(session))


@router.get("/overview", response_model=AnalyticsOverviewResponse)
async def analytics_overview(
    weeks: int = Query(default=DEFAULT_ANALYTICS_WEEKS, ge=1, le=MAX_ANALYTICS_WEEKS),
    owner_id: UUID = Depends(get_authenticated_user_id),
    service: AnalyticsService = Depends(get_analytics_service),
) -> AnalyticsOverviewResponse:
    """Return dashboard aggregates scoped to the signed principal's owner."""
    return await service.overview(owner_id, weeks=weeks)


@router.get("/trends", response_model=AnalyticsTrendsResponse)
async def analytics_trends(
    weeks: int = Query(default=DEFAULT_ANALYTICS_WEEKS, ge=1, le=MAX_ANALYTICS_WEEKS),
    topics_per_week: int = Query(
        default=DEFAULT_TOPICS_PER_WEEK,
        ge=1,
        le=MAX_TOPICS_PER_WEEK,
    ),
    owner_id: UUID = Depends(get_authenticated_user_id),
    service: AnalyticsService = Depends(get_analytics_service),
) -> AnalyticsTrendsResponse:
    """Return bounded owner-scoped analytics time series."""
    return await service.trends(
        owner_id, weeks=weeks, topics_per_week=topics_per_week
    )


@router.get("/recurring-blockers", response_model=RecurringBlockersResponse)
async def recurring_blockers(
    owner_id: UUID = Depends(get_authenticated_user_id),
    service: AnalyticsService = Depends(get_analytics_service),
) -> RecurringBlockersResponse:
    """Return bounded persisted blocker groups within the principal's scope."""
    return await service.recurring_blockers(owner_id)


@router.get(
    "/task-completion-trends", response_model=TaskCompletionTrendsResponse
)
async def task_completion_trends(
    owner_id: UUID = Depends(get_authenticated_user_id),
    service: AnalyticsService = Depends(get_analytics_service),
) -> TaskCompletionTrendsResponse:
    """Report whether historical task-completion trends are measurable."""
    return await service.task_completion_trends(owner_id)


@router.get(
    "/speaker-participation", response_model=SpeakerParticipationResponse
)
async def speaker_participation(
    meetings_limit: int = Query(
        default=DEFAULT_SPEAKER_MEETING_LIMIT,
        ge=1,
        le=MAX_SPEAKER_MEETING_LIMIT,
    ),
    owner_id: UUID = Depends(get_authenticated_user_id),
    service: AnalyticsService = Depends(get_analytics_service),
) -> SpeakerParticipationResponse:
    """Return bounded owner-scoped attributed segment counts per meeting."""
    return await service.speaker_participation(
        owner_id, meetings_limit=meetings_limit
    )


__all__ = ["get_analytics_service", "router"]
