"""Public Gateway facade for meeting-owned result resources."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status

from app.auth.dependencies import get_current_user
from app.routes.meetings import get_meeting_client, _request_id
from app.services.meeting_client import MeetingServiceClient
from shared.database.models.user import User
from shared.schemas.summary import SummaryBase, SummaryCreate, SummaryInDB
from shared.schemas.task import TaskBase, TaskCreate, TaskInDB, TaskUpdate, TaskStatus
from shared.schemas.decision import DecisionBase, DecisionCreate, DecisionInDB
from shared.schemas.followup import FollowupBase, FollowupCreate, FollowupInDB, FollowupUpdate, FollowupStatus
from shared.schemas.pagination import PaginatedResponse, PaginationParams

router = APIRouter(prefix="/meetings/{meeting_id}", tags=["meetings"])


def _identity(request: Request, user: User) -> dict[str, object]:
    return {"user_id": user.id, "request_id": _request_id(request)}


@router.post("/summaries", response_model=SummaryInDB, status_code=status.HTTP_201_CREATED)
async def create_summary(meeting_id: str, payload: SummaryCreate, request: Request, user: User = Depends(get_current_user), client: MeetingServiceClient = Depends(get_meeting_client)) -> SummaryInDB:
    return await client.create_summary(meeting_id, SummaryBase(meeting_id=meeting_id, **payload.model_dump()), **_identity(request, user))


@router.get("/summaries", response_model=PaginatedResponse[SummaryInDB])
async def list_summaries(meeting_id: str, request: Request, pagination: PaginationParams = Depends(), user: User = Depends(get_current_user), client: MeetingServiceClient = Depends(get_meeting_client)) -> PaginatedResponse[SummaryInDB]:
    return await client.list_summaries(meeting_id, page=pagination.page, page_size=pagination.page_size, **_identity(request, user))


@router.get("/summaries/latest", response_model=SummaryInDB)
async def latest_summary(meeting_id: str, request: Request, user: User = Depends(get_current_user), client: MeetingServiceClient = Depends(get_meeting_client)) -> SummaryInDB:
    return await client.get_summary(meeting_id, "", latest=True, **_identity(request, user))


@router.get("/summaries/{summary_id}", response_model=SummaryInDB)
async def get_summary(meeting_id: str, summary_id: str, request: Request, user: User = Depends(get_current_user), client: MeetingServiceClient = Depends(get_meeting_client)) -> SummaryInDB:
    return await client.get_summary(meeting_id, summary_id, **_identity(request, user))


@router.post("/tasks", response_model=TaskInDB, status_code=status.HTTP_201_CREATED)
async def create_task(meeting_id: str, payload: TaskCreate, request: Request, user: User = Depends(get_current_user), client: MeetingServiceClient = Depends(get_meeting_client)) -> TaskInDB:
    return await client.create_task(meeting_id, TaskBase(meeting_id=meeting_id, **payload.model_dump()), **_identity(request, user))


@router.get("/tasks", response_model=PaginatedResponse[TaskInDB])
async def list_tasks(meeting_id: str, request: Request, status_filter: TaskStatus | None = Query(default=None, alias="status"), pagination: PaginationParams = Depends(), user: User = Depends(get_current_user), client: MeetingServiceClient = Depends(get_meeting_client)) -> PaginatedResponse[TaskInDB]:
    return await client.list_tasks(meeting_id, task_status=status_filter.value if status_filter else None, page=pagination.page, page_size=pagination.page_size, **_identity(request, user))


@router.get("/tasks/{task_id}", response_model=TaskInDB)
async def get_task(meeting_id: str, task_id: str, request: Request, user: User = Depends(get_current_user), client: MeetingServiceClient = Depends(get_meeting_client)) -> TaskInDB:
    return await client.get_task(meeting_id, task_id, **_identity(request, user))


@router.patch("/tasks/{task_id}", response_model=TaskInDB)
async def update_task(meeting_id: str, task_id: str, payload: TaskUpdate, request: Request, user: User = Depends(get_current_user), client: MeetingServiceClient = Depends(get_meeting_client)) -> TaskInDB:
    return await client.update_task(meeting_id, task_id, payload, **_identity(request, user))


@router.post("/decisions", response_model=DecisionInDB, status_code=status.HTTP_201_CREATED)
async def create_decision(meeting_id: str, payload: DecisionCreate, request: Request, user: User = Depends(get_current_user), client: MeetingServiceClient = Depends(get_meeting_client)) -> DecisionInDB:
    return await client.create_decision(meeting_id, DecisionBase(meeting_id=meeting_id, **payload.model_dump()), **_identity(request, user))


@router.get("/decisions", response_model=PaginatedResponse[DecisionInDB])
async def list_decisions(meeting_id: str, request: Request, pagination: PaginationParams = Depends(), user: User = Depends(get_current_user), client: MeetingServiceClient = Depends(get_meeting_client)) -> PaginatedResponse[DecisionInDB]:
    return await client.list_decisions(meeting_id, page=pagination.page, page_size=pagination.page_size, **_identity(request, user))


@router.get("/decisions/{decision_id}", response_model=DecisionInDB)
async def get_decision(meeting_id: str, decision_id: str, request: Request, user: User = Depends(get_current_user), client: MeetingServiceClient = Depends(get_meeting_client)) -> DecisionInDB:
    return await client.get_decision(meeting_id, decision_id, **_identity(request, user))


@router.post("/followups", response_model=FollowupInDB, status_code=status.HTTP_201_CREATED)
async def create_followup(meeting_id: str, payload: FollowupCreate, request: Request, user: User = Depends(get_current_user), client: MeetingServiceClient = Depends(get_meeting_client)) -> FollowupInDB:
    return await client.create_followup(meeting_id, FollowupBase(meeting_id=meeting_id, **payload.model_dump()), **_identity(request, user))


@router.get("/followups", response_model=PaginatedResponse[FollowupInDB])
async def list_followups(meeting_id: str, request: Request, status_filter: FollowupStatus | None = Query(default=None, alias="status"), pagination: PaginationParams = Depends(), user: User = Depends(get_current_user), client: MeetingServiceClient = Depends(get_meeting_client)) -> PaginatedResponse[FollowupInDB]:
    return await client.list_followups(meeting_id, followup_status=status_filter.value if status_filter else None, page=pagination.page, page_size=pagination.page_size, **_identity(request, user))


@router.get("/followups/{followup_id}", response_model=FollowupInDB)
async def get_followup(meeting_id: str, followup_id: str, request: Request, user: User = Depends(get_current_user), client: MeetingServiceClient = Depends(get_meeting_client)) -> FollowupInDB:
    return await client.get_followup(meeting_id, followup_id, **_identity(request, user))


@router.patch("/followups/{followup_id}", response_model=FollowupInDB)
async def update_followup(meeting_id: str, followup_id: str, payload: FollowupUpdate, request: Request, user: User = Depends(get_current_user), client: MeetingServiceClient = Depends(get_meeting_client)) -> FollowupInDB:
    return await client.update_followup(meeting_id, followup_id, payload, **_identity(request, user))
