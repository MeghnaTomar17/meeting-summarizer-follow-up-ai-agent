"""Authenticated meeting summary APIs."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_authenticated_user_id
from app.repositories.summary_repository import SummaryRepository
from app.routes.meetings import get_meeting_service
from app.services.meeting_service import MeetingService
from app.services.summary_service import SummaryService
from shared.database.session import get_db_session
from shared.exceptions.common import NotFoundError
from shared.schemas.pagination import PaginationParams, PaginatedResponse, build_paginated_response, paginate_items
from shared.schemas.summary import SummaryBase, SummaryCreate, SummaryInDB

router = APIRouter(prefix="/meetings/{meeting_id}/summaries", tags=["summaries"])


async def get_summary_service(
    session: AsyncSession = Depends(get_db_session),
    meeting_service: MeetingService = Depends(get_meeting_service),
) -> SummaryService:
    return SummaryService(session, SummaryRepository(session), meeting_service)


@router.post("", response_model=SummaryInDB, status_code=status.HTTP_201_CREATED)
async def create_summary(
    meeting_id: str,
    payload: SummaryCreate,
    user_id: UUID = Depends(get_authenticated_user_id),
    service: SummaryService = Depends(get_summary_service),
) -> SummaryInDB:
    return await service.create_summary(
        SummaryBase(meeting_id=meeting_id, **payload.model_dump()), user_id
    )


@router.get("", response_model=PaginatedResponse[SummaryInDB])
async def list_summaries(
    meeting_id: str,
    pagination: PaginationParams = Depends(),
    user_id: UUID = Depends(get_authenticated_user_id),
    service: SummaryService = Depends(get_summary_service),
) -> PaginatedResponse[SummaryInDB]:
    results = await service.list_summaries(meeting_id, user_id)
    page_items, total = paginate_items(results, pagination.page, pagination.page_size)
    return build_paginated_response(page_items, page=pagination.page, page_size=pagination.page_size, total=total)


@router.get("/latest", response_model=SummaryInDB)
async def get_latest_summary(
    meeting_id: str,
    user_id: UUID = Depends(get_authenticated_user_id),
    service: SummaryService = Depends(get_summary_service),
) -> SummaryInDB:
    return await service.get_latest_summary(meeting_id, user_id)


@router.get("/{summary_id}", response_model=SummaryInDB)
async def get_summary(
    meeting_id: str,
    summary_id: str,
    user_id: UUID = Depends(get_authenticated_user_id),
    service: SummaryService = Depends(get_summary_service),
) -> SummaryInDB:
    summary = await service.get_summary(summary_id, user_id)
    if summary.meeting_id != meeting_id:
        raise NotFoundError("Summary not found.")
    return summary
