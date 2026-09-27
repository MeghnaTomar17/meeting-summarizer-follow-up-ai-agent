"""Persistence operations for meeting action items."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.models.task import Task, TaskStatus


class TaskRepository:
    """Database access for tasks; lifecycle rules belong to a service."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, task: Task) -> Task:
        self._session.add(task)
        await self._session.flush()
        return task

    async def get_by_id(self, task_id: UUID) -> Task | None:
        statement = select(Task).where(Task.id == task_id)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def list_by_meeting_id(
        self,
        meeting_id: UUID,
        *,
        status: TaskStatus | None = None,
    ) -> list[Task]:
        statement = select(Task).where(Task.meeting_id == meeting_id)
        if status is not None:
            statement = statement.where(Task.status == status)
        statement = statement.order_by(Task.created_at.desc(), Task.id.desc())
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def update(self, task: Task) -> Task:
        self._session.add(task)
        await self._session.flush()
        return task
