"""Domain use cases for meeting tasks."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.task_repository import TaskRepository
from app.services.meeting_service import MeetingService
from shared.database.models.task import Task, TaskStatus as ORMTaskStatus
from shared.exceptions.common import NotFoundError
from shared.exceptions.common import ValidationError as AppValidationError
from shared.schemas.task import TaskBase, TaskInDB, TaskStatus as SchemaTaskStatus
from shared.schemas.task import TaskUpdate


class TaskService:
    """Coordinate task validation, ownership, persistence, and commits."""

    def __init__(
        self,
        session: AsyncSession,
        task_repository: TaskRepository,
        meeting_service: MeetingService,
    ) -> None:
        self._session = session
        self._task_repository = task_repository
        self._meeting_service = meeting_service

    async def create_task(
        self,
        payload: TaskBase,
        authenticated_user_id: UUID,
    ) -> TaskInDB:
        meeting = await self._meeting_service.require_owned_meeting(
            payload.meeting_id, authenticated_user_id
        )
        assignee_id = (
            self._parse_uuid(payload.assignee_id, "assignee ID")
            if payload.assignee_id is not None
            else None
        )
        task = Task(
            meeting_id=meeting.id,
            title=payload.title,
            description=payload.description,
            assignee_id=assignee_id,
            due_at=payload.due_at,
            status=ORMTaskStatus.OPEN,
        )
        created = await self._task_repository.create(task)
        await self._session.commit()
        return self._to_in_db(created)

    async def get_task(
        self,
        task_id: str,
        authenticated_user_id: UUID,
    ) -> TaskInDB:
        task = await self._task_repository.get_by_id(
            self._parse_uuid(task_id, "task ID")
        )
        if task is None:
            raise NotFoundError("Task not found.")
        await self._meeting_service.require_owned_meeting(
            str(task.meeting_id), authenticated_user_id
        )
        return self._to_in_db(task)

    async def list_tasks(
        self,
        meeting_id: str,
        authenticated_user_id: UUID,
        *,
        status: SchemaTaskStatus | str | None = None,
    ) -> list[TaskInDB]:
        meeting = await self._meeting_service.require_owned_meeting(
            meeting_id, authenticated_user_id
        )
        orm_status = self._to_orm_status(status) if status is not None else None
        tasks = await self._task_repository.list_by_meeting_id(
            meeting.id, status=orm_status
        )
        return [self._to_in_db(task) for task in tasks]

    async def update_task(
        self,
        task_id: str,
        payload: TaskUpdate,
        authenticated_user_id: UUID,
    ) -> TaskInDB:
        task = await self._task_repository.get_by_id(
            self._parse_uuid(task_id, "task ID")
        )
        if task is None:
            raise NotFoundError("Task not found.")
        await self._meeting_service.require_owned_meeting(
            str(task.meeting_id), authenticated_user_id
        )

        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            return self._to_in_db(task)
        if "assignee_id" in changes and changes["assignee_id"] is not None:
            changes["assignee_id"] = self._parse_uuid(
                changes["assignee_id"], "assignee ID"
            )
        if "status" in changes:
            changes["status"] = self._to_orm_status(changes["status"])
        for field_name, value in changes.items():
            setattr(task, field_name, value)

        updated = await self._task_repository.update(task)
        await self._session.commit()
        return self._to_in_db(updated)

    @staticmethod
    def _parse_uuid(value: str, field_name: str) -> UUID:
        try:
            return UUID(value)
        except (TypeError, ValueError) as error:
            raise AppValidationError(f"Invalid {field_name}.") from error

    @staticmethod
    def _to_orm_status(status: SchemaTaskStatus | str) -> ORMTaskStatus:
        value = status.value if isinstance(status, SchemaTaskStatus) else status
        try:
            return ORMTaskStatus(value)
        except (TypeError, ValueError) as error:
            raise AppValidationError("Invalid task status.") from error

    @staticmethod
    def _to_in_db(task: Task) -> TaskInDB:
        return TaskInDB(
            id=str(task.id),
            meeting_id=str(task.meeting_id),
            title=task.title,
            description=task.description,
            assignee_id=str(task.assignee_id) if task.assignee_id is not None else None,
            due_at=task.due_at,
            status=SchemaTaskStatus(task.status.value),
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
