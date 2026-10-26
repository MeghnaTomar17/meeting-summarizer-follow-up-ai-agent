"""Public authenticated interface for structured cross-meeting evidence."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import get_current_user
from app.routes.meetings import get_meeting_client
from app.routes.search import get_search_client
from app.services.meeting_client import MeetingServiceClient
from app.services.search_client import SearchServiceClient
from app.services.ai_client import AIServiceClient
from app.config.settings import GatewaySettings, get_settings
from app.services.cross_meeting_evidence import CrossMeetingEvidenceService
from shared.database.models.user import User
from shared.schemas.cross_meeting import (
    CrossMeetingDataQuery,
    CrossMeetingEvidenceBundle,
    CrossMeetingEvidenceRequest,
    CrossMeetingStructuredData,
    CrossMeetingQuestionRequest,
    CrossMeetingQuestionResponse,
)

router = APIRouter(prefix="/intelligence", tags=["cross-meeting-intelligence"])


def get_cross_meeting_evidence_service(
    meeting_client: MeetingServiceClient = Depends(get_meeting_client),
    search_client: SearchServiceClient = Depends(get_search_client),
    settings: GatewaySettings = Depends(get_settings),
) -> CrossMeetingEvidenceService:
    return CrossMeetingEvidenceService(meeting_client, search_client, AIServiceClient(settings))


@router.post("/structured-data", response_model=CrossMeetingStructuredData)
async def query_structured_data(
    query: CrossMeetingDataQuery,
    request: Request,
    current_user: User = Depends(get_current_user),
    client: MeetingServiceClient = Depends(get_meeting_client),
) -> CrossMeetingStructuredData:
    request_id = getattr(request.state, "request_id", None)
    if not isinstance(request_id, str):
        request_id = None
    return await client.query_cross_meeting_data(
        query, user_id=current_user.id, request_id=request_id
    )


@router.post("/evidence", response_model=CrossMeetingEvidenceBundle)
async def retrieve_cross_meeting_evidence(
    query: CrossMeetingEvidenceRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    service: CrossMeetingEvidenceService = Depends(get_cross_meeting_evidence_service),
) -> CrossMeetingEvidenceBundle:
    request_id = getattr(request.state, "request_id", None)
    if not isinstance(request_id, str):
        request_id = None
    return await service.retrieve(
        query, user_id=current_user.id, request_id=request_id
    )


@router.post("/questions", response_model=CrossMeetingQuestionResponse)
async def answer_cross_meeting_question(
    query: CrossMeetingQuestionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    service: CrossMeetingEvidenceService = Depends(get_cross_meeting_evidence_service),
) -> CrossMeetingQuestionResponse:
    request_id = getattr(request.state, "request_id", None)
    if not isinstance(request_id, str):
        request_id = None
    return await service.answer(query, user_id=current_user.id, request_id=request_id)


__all__ = ["router"]
