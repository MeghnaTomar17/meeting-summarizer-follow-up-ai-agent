"""
Purpose: Internal meeting CRUD routes.
Future responsibilities: Persistence via repositories, status transitions.
Service ownership: meeting-service.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.meeting_repository import MeetingRepository
from app.repositories.transcript_repository import TranscriptRepository
from app.services.meeting_service import MeetingService
from shared.database.session import get_db_session
from shared.schemas.meeting import MeetingCreate, MeetingPublic

router = APIRouter(prefix="/meetings", tags=["meetings"])


async def get_meeting_service(
    session: AsyncSession = Depends(get_db_session),
) -> MeetingService:
    """Build the request-scoped meeting use-case service."""
    return MeetingService(
        session,
        MeetingRepository(session),
        TranscriptRepository(session),
    )


@router.post("", response_model=MeetingPublic, status_code=status.HTTP_201_CREATED)
async def create_meeting(
    payload: MeetingCreate,
    service: MeetingService = Depends(get_meeting_service),
) -> MeetingPublic:
    """Create a meeting through the meeting application service."""
    return await service.create_meeting(payload)


@router.get("/{meeting_id}", response_model=MeetingPublic)
async def get_meeting(
    meeting_id: str,
    service: MeetingService = Depends(get_meeting_service),
) -> MeetingPublic:
    """Return a meeting through the meeting application service."""
    return await service.get_meeting(meeting_id)
