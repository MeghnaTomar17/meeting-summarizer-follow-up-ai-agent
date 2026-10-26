"""Public authenticated semantic-search facade."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import get_current_user
from app.config.settings import GatewaySettings, get_settings
from app.services.search_client import SearchServiceClient
from app.routes.meetings import get_meeting_client
from app.services.meeting_client import MeetingServiceClient
from shared.database.models.user import User
from shared.schemas.semantic_search import (
    SemanticSearchRequest,
    SemanticSearchResponse,
)
from shared.schemas.transcript_indexing import TranscriptIndexingResult
from uuid import UUID

router = APIRouter(prefix="/search", tags=["search"])


def get_search_client(
    settings: GatewaySettings = Depends(get_settings),
) -> SearchServiceClient:
    return SearchServiceClient(settings)


@router.post("", response_model=SemanticSearchResponse)
async def semantic_search(
    payload: SemanticSearchRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    client: SearchServiceClient = Depends(get_search_client),
) -> SemanticSearchResponse:
    """Forward the query with a new Search-audience signed principal."""
    request_id = getattr(request.state, "request_id", None)
    if not isinstance(request_id, str):
        request_id = None
    return await client.search(
        payload,
        user_id=current_user.id,
        request_id=request_id,
    )


@router.post("/meetings/{meeting_id}/index", response_model=TranscriptIndexingResult)
async def index_meeting_transcript(
    meeting_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    meeting_client: MeetingServiceClient = Depends(get_meeting_client),
    search_client: SearchServiceClient = Depends(get_search_client),
) -> TranscriptIndexingResult:
    """Retrieve owned persisted source first, then delegate indexing to Search."""
    request_id = getattr(request.state, "request_id", None)
    if not isinstance(request_id, str):
        request_id = None
    source = await meeting_client.get_transcript_index_source(
        str(meeting_id), user_id=current_user.id, request_id=request_id
    )
    return await search_client.index_transcript(
        meeting_id,
        source,
        user_id=current_user.id,
        request_id=request_id,
    )
