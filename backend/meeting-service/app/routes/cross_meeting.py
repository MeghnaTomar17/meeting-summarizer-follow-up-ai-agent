"""Authenticated internal structured evidence access across owned meetings."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_authenticated_user_id
from app.repositories.cross_meeting_repository import CrossMeetingRepository
from app.services.cross_meeting_service import CrossMeetingService
from shared.database.session import get_db_session
from shared.schemas.cross_meeting import CrossMeetingDataQuery, CrossMeetingStructuredData

router = APIRouter(prefix="/intelligence", tags=["cross-meeting-intelligence"])


async def get_cross_meeting_service(
    session: AsyncSession = Depends(get_db_session),
) -> CrossMeetingService:
    return CrossMeetingService(CrossMeetingRepository(session))


@router.post("/structured-data", response_model=CrossMeetingStructuredData)
async def query_structured_data(
    query: CrossMeetingDataQuery,
    owner_id: UUID = Depends(get_authenticated_user_id),
    service: CrossMeetingService = Depends(get_cross_meeting_service),
) -> CrossMeetingStructuredData:
    """Return bounded evidence scoped to the owner in the signed principal."""
    return await service.query(query, owner_id=owner_id)


__all__ = ["get_cross_meeting_service", "router"]
