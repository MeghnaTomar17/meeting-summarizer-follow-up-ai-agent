"""
Purpose: Transcript retrieval and ingestion routes.
Future responsibilities: Segment storage, STT callback webhooks.
Service ownership: meeting-service.

NOTE: Semantic/text chunking for embeddings and RAG is owned by search-service
(see search-service/chunking/). This service stores transcript segments and metadata only.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.dependencies import get_authenticated_user_id
from app.routes.meetings import get_meeting_service
from app.services.meeting_service import MeetingService
from shared.schemas.transcript import TranscriptBase, TranscriptInDB, TranscriptWrite

router = APIRouter(prefix="/meetings", tags=["transcripts"])


@router.post(
    "/{meeting_id}/transcript",
    response_model=TranscriptInDB,
    status_code=status.HTTP_201_CREATED,
)
async def create_transcript(
    meeting_id: str,
    payload: TranscriptWrite,
    authenticated_user_id: UUID = Depends(get_authenticated_user_id),
    service: MeetingService = Depends(get_meeting_service),
) -> TranscriptInDB:
    """Create a meeting transcript using the authoritative path meeting ID."""
    return await service.create_transcript(
        TranscriptBase(
            meeting_id=meeting_id,
            segments=payload.segments,
            language=payload.language,
        ),
        authenticated_user_id,
    )


@router.get("/{meeting_id}/transcript", response_model=TranscriptInDB)
async def get_transcript(
    meeting_id: str,
    authenticated_user_id: UUID = Depends(get_authenticated_user_id),
    service: MeetingService = Depends(get_meeting_service),
) -> TranscriptInDB:
    """Return a meeting transcript through the meeting application service."""
    return await service.get_transcript(meeting_id, authenticated_user_id)


@router.put("/{meeting_id}/transcript", response_model=TranscriptInDB)
async def replace_transcript(
    meeting_id: str,
    payload: TranscriptWrite,
    authenticated_user_id: UUID = Depends(get_authenticated_user_id),
    service: MeetingService = Depends(get_meeting_service),
) -> TranscriptInDB:
    """Replace an existing meeting transcript through the application service."""
    return await service.replace_transcript(
        meeting_id,
        segments=payload.segments,
        language=payload.language,
        authenticated_user_id=authenticated_user_id,
    )
