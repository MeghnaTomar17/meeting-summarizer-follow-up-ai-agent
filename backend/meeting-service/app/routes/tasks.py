"""Authenticated meeting task APIs."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_authenticated_user_id
from app.repositories.task_repository import TaskRepository
from app.routes.meetings import get_meeting_service
from app.services.meeting_service import MeetingService
from app.services.task_service import TaskService
from shared.database.session import get_db_session
from shared.exceptions.common import NotFoundError
from shared.schemas.task import TaskBase, TaskCreate, TaskInDB, TaskStatus, TaskUpdate
from shared.schemas.pagination import PaginationParams, PaginatedResponse, build_paginated_response, paginate_items

router = APIRouter(prefix="/meetings/{meeting_id}/tasks", tags=["tasks"])


async def get_task_service(session: AsyncSession = Depends(get_db_session), meeting_service: MeetingService = Depends(get_meeting_service)) -> TaskService:
    return TaskService(session, TaskRepository(session), meeting_service)


@router.post("", response_model=TaskInDB, status_code=status.HTTP_201_CREATED)
async def create_task(meeting_id: str, payload: TaskCreate, user_id: UUID = Depends(get_authenticated_user_id), service: TaskService = Depends(get_task_service)) -> TaskInDB:
    return await service.create_task(TaskBase(meeting_id=meeting_id, **payload.model_dump()), user_id)


@router.get("", response_model=PaginatedResponse[TaskInDB])
async def list_tasks(meeting_id: str, status_filter: TaskStatus | None = Query(default=None, alias="status"), pagination: PaginationParams = Depends(), user_id: UUID = Depends(get_authenticated_user_id), service: TaskService = Depends(get_task_service)) -> PaginatedResponse[TaskInDB]:
    results = await service.list_tasks(meeting_id, user_id, status=status_filter)
    page_items, total = paginate_items(results, pagination.page, pagination.page_size)
    return build_paginated_response(page_items, page=pagination.page, page_size=pagination.page_size, total=total)


@router.get("/{task_id}", response_model=TaskInDB)
async def get_task(meeting_id: str, task_id: str, user_id: UUID = Depends(get_authenticated_user_id), service: TaskService = Depends(get_task_service)) -> TaskInDB:
    task = await service.get_task(task_id, user_id)
    if task.meeting_id != meeting_id:
        raise NotFoundError("Task not found.")
    return task


@router.patch("/{task_id}", response_model=TaskInDB)
async def update_task(meeting_id: str, task_id: str, payload: TaskUpdate, user_id: UUID = Depends(get_authenticated_user_id), service: TaskService = Depends(get_task_service)) -> TaskInDB:
    existing = await service.get_task(task_id, user_id)
    if existing.meeting_id != meeting_id:
        raise NotFoundError("Task not found.")
    task = await service.update_task(task_id, payload, user_id)
    return task
