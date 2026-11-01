"""PostgreSQL operations for owner-scoped submission idempotency."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.models.meeting_submission_idempotency import MeetingSubmissionIdempotency


class MeetingSubmissionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim(
        self,
        *,
        owner_id: UUID,
        operation: str,
        idempotency_key: str,
    ) -> tuple[UUID, MeetingSubmissionIdempotency | None]:
        """Serialize the owner/key pair transactionally, then find its record."""
        record_id = uuid4()
        # Transaction-scoped PostgreSQL advisory locks serialize concurrent
        # attempts for this scope. The unique index remains the final invariant.
        await self._session.execute(
            select(
                func.pg_advisory_xact_lock(
                    func.hashtext(str(owner_id)),
                    func.hashtext(f"{operation}:{idempotency_key}"),
                )
            )
        )
        existing = await self._session.scalar(
            select(MeetingSubmissionIdempotency)
            .where(
                MeetingSubmissionIdempotency.owner_id == owner_id,
                MeetingSubmissionIdempotency.operation == operation,
                MeetingSubmissionIdempotency.idempotency_key == idempotency_key,
            )
            .with_for_update()
        )
        if existing is None:
            return record_id, None
        return existing.id, existing

    async def complete(
        self,
        record_id: UUID,
        *,
        owner_id: UUID,
        operation: str,
        idempotency_key: str,
        request_hash: str,
        meeting_id: UUID,
        transcript_id: UUID,
        job_id: UUID,
    ) -> None:
        self._session.add(
            MeetingSubmissionIdempotency(
                id=record_id,
                owner_id=owner_id,
                operation=operation,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                meeting_id=meeting_id,
                transcript_id=transcript_id,
                job_id=job_id,
            )
        )
        await self._session.flush()


__all__ = ["MeetingSubmissionRepository"]
