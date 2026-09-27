"""Authenticated meeting follow-up APIs."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_authenticated_user_id
from app.repositories.followup_repository import FollowupRepository
from app.routes.meetings import get_meeting_service
from app.services.followup_service import FollowUpService
from app.services.meeting_service import MeetingService
from shared.database.session import get_db_session
from shared.exceptions.common import NotFoundError
from shared.schemas.followup import (
    FollowupBase,
    FollowupCreate,
    FollowupInDB,
    FollowupStatus,
    FollowupUpdate,
)
from shared.schemas.pagination import PaginationParams, PaginatedResponse, build_paginated_response, paginate_items

router = APIRouter(prefix="/meetings/{meeting_id}/followups", tags=["follow-ups"])


async def get_followup_service(
    session: AsyncSession = Depends(get_db_session),
    meeting_service: MeetingService = Depends(get_meeting_service),
) -> FollowUpService:
    return FollowUpService(session, FollowupRepository(session), meeting_service)


@router.post("", response_model=FollowupInDB, status_code=status.HTTP_201_CREATED)
async def create_followup(
    meeting_id: str,
    payload: FollowupCreate,
    user_id: UUID = Depends(get_authenticated_user_id),
    service: FollowUpService = Depends(get_followup_service),
) -> FollowupInDB:
    return await service.create_followup(
        FollowupBase(meeting_id=meeting_id, **payload.model_dump()), user_id
    )


@router.get("", response_model=PaginatedResponse[FollowupInDB])
async def list_followups(
    meeting_id: str,
    status_filter: FollowupStatus | None = Query(default=None, alias="status"),
    pagination: PaginationParams = Depends(),
    user_id: UUID = Depends(get_authenticated_user_id),
    service: FollowUpService = Depends(get_followup_service),
) -> PaginatedResponse[FollowupInDB]:
    results = await service.list_followups(meeting_id, user_id, status=status_filter)
    page_items, total = paginate_items(results, pagination.page, pagination.page_size)
    return build_paginated_response(page_items, page=pagination.page, page_size=pagination.page_size, total=total)


@router.get("/{followup_id}", response_model=FollowupInDB)
async def get_followup(
    meeting_id: str,
    followup_id: str,
    user_id: UUID = Depends(get_authenticated_user_id),
    service: FollowUpService = Depends(get_followup_service),
) -> FollowupInDB:
    followup = await service.get_followup(followup_id, user_id)
    if followup.meeting_id != meeting_id:
        raise NotFoundError("Follow-up not found.")
    return followup


@router.patch("/{followup_id}", response_model=FollowupInDB)
async def update_followup(
    meeting_id: str,
    followup_id: str,
    payload: FollowupUpdate,
    user_id: UUID = Depends(get_authenticated_user_id),
    service: FollowUpService = Depends(get_followup_service),
) -> FollowupInDB:
    existing = await service.get_followup(followup_id, user_id)
    if existing.meeting_id != meeting_id:
        raise NotFoundError("Follow-up not found.")
    followup = await service.update_followup(followup_id, payload, user_id)
    return followup
