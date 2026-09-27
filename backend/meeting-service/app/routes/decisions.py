"""Authenticated meeting decision APIs."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_authenticated_user_id
from app.repositories.decision_repository import DecisionRepository
from app.routes.meetings import get_meeting_service
from app.services.decision_service import DecisionService
from app.services.meeting_service import MeetingService
from shared.database.session import get_db_session
from shared.exceptions.common import NotFoundError
from shared.schemas.decision import DecisionBase, DecisionCreate, DecisionInDB
from shared.schemas.pagination import PaginationParams, PaginatedResponse, build_paginated_response, paginate_items

router = APIRouter(prefix="/meetings/{meeting_id}/decisions", tags=["decisions"])


async def get_decision_service(
    session: AsyncSession = Depends(get_db_session),
    meeting_service: MeetingService = Depends(get_meeting_service),
) -> DecisionService:
    return DecisionService(session, DecisionRepository(session), meeting_service)


@router.post("", response_model=DecisionInDB, status_code=status.HTTP_201_CREATED)
async def create_decision(
    meeting_id: str,
    payload: DecisionCreate,
    user_id: UUID = Depends(get_authenticated_user_id),
    service: DecisionService = Depends(get_decision_service),
) -> DecisionInDB:
    return await service.create_decision(
        DecisionBase(meeting_id=meeting_id, **payload.model_dump()), user_id
    )


@router.get("", response_model=PaginatedResponse[DecisionInDB])
async def list_decisions(
    meeting_id: str,
    pagination: PaginationParams = Depends(),
    user_id: UUID = Depends(get_authenticated_user_id),
    service: DecisionService = Depends(get_decision_service),
) -> PaginatedResponse[DecisionInDB]:
    results = await service.list_decisions(meeting_id, user_id)
    page_items, total = paginate_items(results, pagination.page, pagination.page_size)
    return build_paginated_response(page_items, page=pagination.page, page_size=pagination.page_size, total=total)


@router.get("/{decision_id}", response_model=DecisionInDB)
async def get_decision(
    meeting_id: str,
    decision_id: str,
    user_id: UUID = Depends(get_authenticated_user_id),
    service: DecisionService = Depends(get_decision_service),
) -> DecisionInDB:
    decision = await service.get_decision(decision_id, user_id)
    if decision.meeting_id != meeting_id:
        raise NotFoundError("Decision not found.")
    return decision
