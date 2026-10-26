"""Authenticated public dashboard analytics facade."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.auth.dependencies import get_current_user
from app.routes.meetings import _request_id, get_meeting_client
from shared.database.models.user import User
from shared.schemas.analytics import (
    DEFAULT_ANALYTICS_WEEKS,
    DEFAULT_TOPICS_PER_WEEK,
    MAX_ANALYTICS_WEEKS,
    MAX_TOPICS_PER_WEEK,
    AnalyticsOverviewResponse,
    AnalyticsTrendsResponse,
    RecurringBlockersResponse,
    DEFAULT_SPEAKER_MEETING_LIMIT,
    MAX_SPEAKER_MEETING_LIMIT,
    SpeakerParticipationResponse,
    TaskCompletionTrendsResponse,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview", response_model=AnalyticsOverviewResponse)
async def analytics_overview(
    request: Request,
    weeks: int = Query(
        default=DEFAULT_ANALYTICS_WEEKS,
        ge=1,
        le=MAX_ANALYTICS_WEEKS,
    ),
    current_user: User = Depends(get_current_user),
    client: MeetingServiceClient = Depends(get_meeting_client),
) -> AnalyticsOverviewResponse:
    """Proxy owner-scoped analytics through Meeting Service."""
    return await client.get_analytics_overview(
        weeks=weeks,
        user_id=current_user.id,
        request_id=_request_id(request),
    )


@router.get("/trends", response_model=AnalyticsTrendsResponse)
async def analytics_trends(
    request: Request,
    weeks: int = Query(
        default=DEFAULT_ANALYTICS_WEEKS,
        ge=1,
        le=MAX_ANALYTICS_WEEKS,
    ),
    topics_per_week: int = Query(
        default=DEFAULT_TOPICS_PER_WEEK,
        ge=1,
        le=MAX_TOPICS_PER_WEEK,
    ),
    current_user: User = Depends(get_current_user),
    client=Depends(get_meeting_client),
) -> AnalyticsTrendsResponse:
    """Proxy owner-scoped analytics trends through Meeting Service."""
    return await client.get_analytics_trends(
        weeks=weeks,
        topics_per_week=topics_per_week,
        user_id=current_user.id,
        request_id=_request_id(request),
    )


@router.get("/recurring-blockers", response_model=RecurringBlockersResponse)
async def recurring_blockers(
    request: Request,
    current_user: User = Depends(get_current_user),
    client=Depends(get_meeting_client),
) -> RecurringBlockersResponse:
    """Proxy owner-scoped recurring blocker analytics through Meeting Service."""
    return await client.get_recurring_blockers(
        user_id=current_user.id,
        request_id=_request_id(request),
    )


@router.get(
    "/task-completion-trends", response_model=TaskCompletionTrendsResponse
)
async def task_completion_trends(
    request: Request,
    current_user: User = Depends(get_current_user),
    client=Depends(get_meeting_client),
) -> TaskCompletionTrendsResponse:
    """Proxy the task-completion history capability through Meeting Service."""
    return await client.get_task_completion_trends(
        user_id=current_user.id,
        request_id=_request_id(request),
    )


@router.get("/speaker-participation", response_model=SpeakerParticipationResponse)
async def speaker_participation(
    request: Request,
    meetings_limit: int = Query(
        default=DEFAULT_SPEAKER_MEETING_LIMIT,
        ge=1,
        le=MAX_SPEAKER_MEETING_LIMIT,
    ),
    current_user: User = Depends(get_current_user),
    client=Depends(get_meeting_client),
) -> SpeakerParticipationResponse:
    """Proxy bounded per-meeting transcript segment counts."""
    return await client.get_speaker_participation(
        meetings_limit=meetings_limit,
        user_id=current_user.id,
        request_id=_request_id(request),
    )


__all__ = ["router"]
