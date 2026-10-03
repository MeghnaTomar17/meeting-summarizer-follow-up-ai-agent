"""PostgreSQL repository for durable processing-job lifecycle rows."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.models.processing_job import ProcessingJobRecord


class ProcessingJobRepository:
    """Data access only; transaction ownership stays in ProcessingJobService."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_if_absent(self, record: ProcessingJobRecord) -> ProcessingJobRecord:
        statement = (
            insert(ProcessingJobRecord)
            .values(**{
                column.name: getattr(record, column.name)
                for column in ProcessingJobRecord.__table__.columns
                if column.name not in {"created_at", "updated_at"}
            })
            .on_conflict_do_nothing(index_elements=[ProcessingJobRecord.job_id])
        )
        await self._session.execute(statement)
        await self._session.flush()
        return await self.get_by_id(record.job_id)

    async def get_by_id(self, job_id: UUID, *, for_update: bool = False) -> ProcessingJobRecord | None:
        statement = select(ProcessingJobRecord).where(ProcessingJobRecord.job_id == job_id)
        if for_update:
            statement = statement.with_for_update()
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def update(self, record: ProcessingJobRecord) -> ProcessingJobRecord:
        await self._session.flush()
        return record
