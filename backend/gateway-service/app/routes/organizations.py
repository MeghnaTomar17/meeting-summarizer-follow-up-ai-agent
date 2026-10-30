"""Authenticated organization read routes delegated to Meeting Service."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import get_current_user
from app.routes.meetings import get_meeting_client
from app.services.meeting_client import MeetingServiceClient
from shared.database.models.user import User
from shared.schemas.organization import PersonalOrganizationResponse

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("/personal", response_model=PersonalOrganizationResponse)
async def get_personal_organization(
    request: Request,
    current_user: User = Depends(get_current_user),
    client: MeetingServiceClient = Depends(get_meeting_client),
) -> PersonalOrganizationResponse:
    return await client.get_personal_organization(
        user_id=current_user.id,
        request_id=getattr(request.state, "request_id", None),
    )
