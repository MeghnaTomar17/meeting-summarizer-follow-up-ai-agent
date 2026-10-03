"""Application orchestration for registering and publishing one logical job."""

from __future__ import annotations

from typing import Protocol

from app.background_processing import (
    AIProcessingJob,
    AIProcessingJobStatus,
    InvalidJobTransitionError,
    JobSubmissionReceipt,
)


class DurableJobRegistrar(Protocol):
    async def register(
        self,
        *,
        job_id,
        meeting_id,
        transcript_id,
        owner_id,
        requested_operations: list[str],
    ): ...


class ApplicationJobSubmissionService:
    """Persist the application job before handing it to Celery transport.

    Retrying the same application job ID is idempotent at the database row;
    the broker may receive duplicates, which the worker claims atomically.
    """

    def __init__(self, registrar: DurableJobRegistrar, publisher) -> None:
        self._registrar = registrar
        self._publisher = publisher

    @classmethod
    def from_settings(cls, publisher):
        """Build the PostgreSQL lifecycle coordinator and Celery publisher."""
        from app.config.settings import get_settings
        from app.celery_submission import CeleryJobSubmissionPort
        from shared.jobs.lifecycle import PostgresJobLifecycle

        settings = get_settings()
        lifecycle = PostgresJobLifecycle(settings)
        instance = cls(
            lifecycle,
            CeleryJobSubmissionPort.from_settings(publisher, settings),
        )
        instance._owned_lifecycle = lifecycle
        return instance

    async def submit(self, job: AIProcessingJob) -> JobSubmissionReceipt:
        if job.status != AIProcessingJobStatus.QUEUED:
            raise InvalidJobTransitionError("Only queued jobs can be submitted.")
        if (
            job.execution_context is None
            or not job.execution_context.was_issued_by_authenticated_boundary
            or job.execution_context_id != job.execution_context.context_id
            or job.execution_principal_id != job.execution_context.user_id
            or job.context is not None
        ):
            raise ValueError("A bound authenticated job is required.")
        if job.context is not None:
            from app.celery_submission import UnsupportedQueueJobError

            raise UnsupportedQueueJobError("Free-form processing context is not supported in queue messages.")
        record = await self._registrar.register(
            job_id=job.job_id,
            meeting_id=job.meeting_id,
            transcript_id=job.transcript_id,
            owner_id=job.execution_principal_id,
            requested_operations=[item.value for item in job.requested_operations],
        )
        if getattr(record, "status", AIProcessingJobStatus.QUEUED.value) != AIProcessingJobStatus.QUEUED.value:
            raise InvalidJobTransitionError("Only queued application jobs may be published.")
        return await self._publisher.submit(job)

    async def aclose(self) -> None:
        lifecycle = getattr(self, "_owned_lifecycle", None)
        if lifecycle is not None:
            await lifecycle.aclose()


__all__ = ["ApplicationJobSubmissionService", "DurableJobRegistrar"]
