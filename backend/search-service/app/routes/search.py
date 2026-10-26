"""Authenticated Search Service retrieval route."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_authenticated_user_id
from app.dependencies import get_semantic_search_service, get_transcript_indexing_service
from indexing.service import TranscriptIndexingService
from retrieval.contracts import (
    SearchAuthorizationScope,
    SemanticSearchRequest,
    SemanticSearchResponse,
)
from retrieval.semantic_search import SemanticSearch
from shared.schemas.transcript_indexing import TranscriptIndexSource, TranscriptIndexingResult

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SemanticSearchResponse)
async def semantic_search(
    payload: SemanticSearchRequest,
    user_id: UUID = Depends(get_authenticated_user_id),
    service: SemanticSearch = Depends(get_semantic_search_service),
) -> SemanticSearchResponse:
    """Search only chunks owned by the user asserted in the signed principal."""
    return await service.search(
        payload,
        scope=SearchAuthorizationScope(owner_id=user_id),
    )


@router.post("/meetings/{meeting_id}/index", response_model=TranscriptIndexingResult)
async def index_meeting_transcript(
    meeting_id: UUID,
    source: TranscriptIndexSource,
    user_id: UUID = Depends(get_authenticated_user_id),
    service: TranscriptIndexingService = Depends(get_transcript_indexing_service),
) -> TranscriptIndexingResult:
    """Index a Gateway-fetched persisted transcript under the signed owner."""
    return await service.index(source, meeting_id=meeting_id, owner_id=user_id)
