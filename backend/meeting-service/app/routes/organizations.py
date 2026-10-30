"""Internal organization reads authenticated by Gateway principals."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_authenticated_user_id
from app.repositories.meeting_repository import MeetingRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.transcript_repository import TranscriptRepository
from app.services.meeting_service import MeetingService
from shared.database.session import get_db_session
from shared.schemas.organization import PersonalOrganizationResponse

router = APIRouter(prefix="/organizations", tags=["organizations"])


async def get_organization_service(
    session: AsyncSession = Depends(get_db_session),
) -> MeetingService:
    return MeetingService(
        session,
        MeetingRepository(session),
        TranscriptRepository(session),
        OrganizationRepository(session),
    )


@router.get("/personal", response_model=PersonalOrganizationResponse)
async def get_personal_organization(
    user_id: UUID = Depends(get_authenticated_user_id),
    service: MeetingService = Depends(get_organization_service),
) -> PersonalOrganizationResponse:
    return await service.get_personal_organization(user_id)
