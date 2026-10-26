"""Owner-scoped read resources for meeting details."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from app.auth.dependencies import get_authenticated_user_id
from app.routes.meetings import get_meeting_service
from app.services.meeting_service import MeetingService
from shared.schemas.meeting_insight import MeetingInsightInDB
from shared.schemas.pagination import PaginatedResponse, PaginationParams
from shared.schemas.processing_status import MeetingProcessingStatus

router = APIRouter(prefix="/meetings/{meeting_id}", tags=["meetings"])


@router.get("/insights", response_model=PaginatedResponse[MeetingInsightInDB])
async def list_meeting_insights(
    meeting_id: str,
    pagination: PaginationParams = Depends(),
    authenticated_user_id: UUID = Depends(get_authenticated_user_id),
    service: MeetingService = Depends(get_meeting_service),
) -> PaginatedResponse[MeetingInsightInDB]:
    return await service.list_meeting_insights(
        meeting_id,
        authenticated_user_id,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/processing-status", response_model=MeetingProcessingStatus)
async def get_meeting_processing_status(
    meeting_id: str,
    authenticated_user_id: UUID = Depends(get_authenticated_user_id),
    service: MeetingService = Depends(get_meeting_service),
) -> MeetingProcessingStatus:
    return await service.get_processing_status(meeting_id, authenticated_user_id)
