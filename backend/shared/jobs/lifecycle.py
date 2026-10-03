"""Application-owned processing-job lifecycle and bounded retry policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from shared.database.models.processing_job import ProcessingJobRecord
from shared.jobs.repository import ProcessingJobRepository


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


VALID_TRANSITIONS = {
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING, JobStatus.FAILED}),
    # RUNNING -> RUNNING is an expired-lease reclaim, protected by a new token.
    JobStatus.RUNNING: frozenset({JobStatus.RUNNING, JobStatus.QUEUED, JobStatus.COMPLETED, JobStatus.PARTIAL, JobStatus.FAILED}),
    JobStatus.COMPLETED: frozenset(),
    JobStatus.PARTIAL: frozenset(),
    JobStatus.FAILED: frozenset(),
}


class FailureCategory(StrEnum):
    TRANSIENT_INFRASTRUCTURE = "transient_infrastructure"
    PERMANENT_VALIDATION = "permanent_validation"
    SECURITY = "security"
    APPLICATION_PROCESSING = "application_processing"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"


_SAFE_FAILURE_MESSAGES = {
    FailureCategory.TRANSIENT_INFRASTRUCTURE: "A temporary processing dependency failed.",
    FailureCategory.PERMANENT_VALIDATION: "The job input or requested transcript is invalid or unavailable.",
    FailureCategory.SECURITY: "The processing job could not be authorized.",
    FailureCategory.APPLICATION_PROCESSING: "AI processing failed for the requested operations.",
    FailureCategory.ATTEMPTS_EXHAUSTED: "The processing job exhausted its retry attempts.",
}


class LifecycleIdentityError(ValueError):
    """The signed identity/envelope does not match the registered job."""


class JobTargetRejectedError(ValueError):
    """MeetingService rejected the verified user/meeting/transcript target."""

    def __init__(self, category: FailureCategory = FailureCategory.SECURITY) -> None:
        self.category = category
        super().__init__("The processing target is not authorized or available.")


@dataclass(frozen=True)
class ClaimResult:
    outcome: str
    status: JobStatus
    attempt: int
    lease_token: UUID | None = None
    retry_after_seconds: float | None = None


@dataclass(frozen=True)
class FailureResult:
    status: JobStatus
    retry: bool
    retry_after_seconds: float | None
    attempt: int


class ProcessingJobService:
    """Own lifecycle transitions, attempt counts and application retry rules."""

    def __init__(
        self,
        session: AsyncSession,
        repository: ProcessingJobRepository,
        *,
        max_attempts: int = 3,
        retry_base_seconds: float = 2.0,
        retry_max_seconds: float = 60.0,
        lease_seconds: int = 960,
    ) -> None:
        if max_attempts < 1 or retry_base_seconds <= 0 or retry_max_seconds < retry_base_seconds or lease_seconds < 1:
            raise ValueError("Invalid processing job reliability settings.")
        self._session = session
        self._repository = repository
        self._max_attempts = max_attempts
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds
        self._lease_seconds = lease_seconds

    async def register(
        self,
        *,
        job_id: UUID,
        meeting_id: UUID,
        transcript_id: UUID,
        owner_id: UUID,
        requested_operations: list[str],
    ) -> ProcessingJobRecord:
        async with self._session.begin():
            requested = ProcessingJobRecord(
                job_id=job_id,
                meeting_id=meeting_id,
                transcript_id=transcript_id,
                owner_id=owner_id,
                requested_operations=list(requested_operations),
                status=JobStatus.QUEUED.value,
                attempt_count=0,
                max_attempts=self._max_attempts,
            )
            stored = await self._repository.create_if_absent(requested)
            if not self._matches(stored, meeting_id, transcript_id, owner_id, requested_operations):
                raise LifecycleIdentityError("The job ID is already registered to different input.")
            return stored

    async def claim(
        self,
        *,
        job_id: UUID,
        meeting_id: UUID,
        transcript_id: UUID,
        owner_id: UUID,
        requested_operations: list[str],
        now: datetime | None = None,
    ) -> ClaimResult:
        current = now or datetime.now(timezone.utc)
        async with self._session.begin():
            record = await self._repository.get_by_id(job_id, for_update=True)
            if record is None or not self._matches(record, meeting_id, transcript_id, owner_id, requested_operations):
                raise LifecycleIdentityError("The verified job does not match a registered job.")
            status = JobStatus(record.status)
            if status in {JobStatus.COMPLETED, JobStatus.PARTIAL, JobStatus.FAILED}:
                return ClaimResult("terminal", status, record.attempt_count)
            if status == JobStatus.RUNNING and record.lease_expires_at and record.lease_expires_at > current:
                return ClaimResult(
                    "already_running", status, record.attempt_count,
                    retry_after_seconds=max(1.0, (record.lease_expires_at - current).total_seconds()),
                )
            if record.next_attempt_at and record.next_attempt_at > current:
                return ClaimResult(
                    "not_due", JobStatus.QUEUED, record.attempt_count,
                    retry_after_seconds=max(1.0, (record.next_attempt_at - current).total_seconds()),
                )
            if record.attempt_count >= record.max_attempts:
                self._transition(record, JobStatus.FAILED)
                record.failure_category = FailureCategory.ATTEMPTS_EXHAUSTED.value
                record.failure_message = _SAFE_FAILURE_MESSAGES[FailureCategory.ATTEMPTS_EXHAUSTED]
                record.completed_at = current
                record.lease_token = None
                record.lease_expires_at = None
                await self._repository.update(record)
                return ClaimResult("terminal", JobStatus.FAILED, record.attempt_count)
            lease = uuid4()
            self._transition(record, JobStatus.RUNNING)
            record.attempt_count += 1
            record.started_at = record.started_at or current
            record.lease_token = lease
            record.lease_expires_at = current + timedelta(seconds=self._lease_seconds)
            record.last_attempt_at = current
            record.next_attempt_at = None
            record.failure_category = None
            record.failure_message = None
            await self._repository.update(record)
            return ClaimResult("claimed", JobStatus.RUNNING, record.attempt_count, lease)

    async def validate_registered(
        self,
        *,
        job_id: UUID,
        meeting_id: UUID,
        transcript_id: UUID,
        owner_id: UUID,
        requested_operations: list[str],
        now: datetime | None = None,
    ) -> ClaimResult:
        """Read and bind the row after signature verification, before ownership preflight."""
        record = await self._repository.get_by_id(job_id)
        if record is None or not self._matches(record, meeting_id, transcript_id, owner_id, requested_operations):
            raise LifecycleIdentityError("The verified job does not match a registered job.")
        status = JobStatus(record.status)
        remaining = None
        current = now or datetime.now(timezone.utc)
        due_at = record.lease_expires_at if status == JobStatus.RUNNING else record.next_attempt_at
        if due_at is not None and due_at > current:
            remaining = max(1.0, (due_at - current).total_seconds())
        return ClaimResult("registered", status, record.attempt_count, record.lease_token, remaining)

    async def reject_before_claim(
        self,
        *,
        job_id: UUID,
        meeting_id: UUID,
        transcript_id: UUID,
        owner_id: UUID,
        requested_operations: list[str],
        expected_status: JobStatus,
        expected_lease_token: UUID | None,
        category: FailureCategory = FailureCategory.SECURITY,
    ) -> bool:
        """Record verified-target rejection without incrementing execution attempts."""
        async with self._session.begin():
            record = await self._repository.get_by_id(job_id, for_update=True)
            if (
                record is None
                or not self._matches(record, meeting_id, transcript_id, owner_id, requested_operations)
                or JobStatus(record.status) != expected_status
                or record.lease_token != expected_lease_token
            ):
                return False
            if expected_status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
                return False
            self._transition(record, JobStatus.FAILED)
            record.failure_category = category.value
            record.failure_message = _SAFE_FAILURE_MESSAGES[category]
            record.completed_at = datetime.now(timezone.utc)
            record.next_attempt_at = None
            record.lease_token = None
            record.lease_expires_at = None
            await self._repository.update(record)
            return True

    async def complete(
        self, job_id: UUID, lease_token: UUID, *, status: JobStatus, result: dict[str, Any]
    ) -> bool:
        if status not in {JobStatus.COMPLETED, JobStatus.PARTIAL}:
            raise ValueError("Successful completion must be completed or partial.")
        async with self._session.begin():
            record = await self._repository.get_by_id(job_id, for_update=True)
            if record is None or record.status != JobStatus.RUNNING.value or record.lease_token != lease_token:
                return False
            self._transition(record, status)
            record.result = result
            record.completed_at = datetime.now(timezone.utc)
            record.lease_token = None
            record.lease_expires_at = None
            await self._repository.update(record)
            return True

    async def fail(
        self,
        job_id: UUID,
        lease_token: UUID,
        *,
        category: FailureCategory,
        retryable: bool,
        now: datetime | None = None,
    ) -> FailureResult:
        current = now or datetime.now(timezone.utc)
        safe_message = _SAFE_FAILURE_MESSAGES[category]
        async with self._session.begin():
            record = await self._repository.get_by_id(job_id, for_update=True)
            if record is None or record.status != JobStatus.RUNNING.value or record.lease_token != lease_token:
                return FailureResult(JobStatus.FAILED, False, None, 0 if record is None else record.attempt_count)
            should_retry = retryable and category == FailureCategory.TRANSIENT_INFRASTRUCTURE and record.attempt_count < record.max_attempts
            record.failure_category = category.value
            record.failure_message = safe_message
            record.lease_token = None
            record.lease_expires_at = None
            if should_retry:
                delay = min(self._retry_max_seconds, self._retry_base_seconds * (2 ** (record.attempt_count - 1)))
                self._transition(record, JobStatus.QUEUED)
                record.next_attempt_at = current + timedelta(seconds=delay)
                record.completed_at = None
                await self._repository.update(record)
                return FailureResult(JobStatus.QUEUED, True, delay, record.attempt_count)
            if retryable and category == FailureCategory.TRANSIENT_INFRASTRUCTURE:
                record.failure_category = FailureCategory.ATTEMPTS_EXHAUSTED.value
                record.failure_message = _SAFE_FAILURE_MESSAGES[FailureCategory.ATTEMPTS_EXHAUSTED]
            self._transition(record, JobStatus.FAILED)
            record.completed_at = current
            record.next_attempt_at = None
            await self._repository.update(record)
            return FailureResult(JobStatus.FAILED, False, None, record.attempt_count)

    @staticmethod
    def _transition(record: ProcessingJobRecord, target: JobStatus) -> None:
        current = JobStatus(record.status)
        if target not in VALID_TRANSITIONS[current]:
            raise ValueError(f"Invalid processing job transition: {current.value} -> {target.value}.")
        record.status = target.value

    @staticmethod
    def _matches(record, meeting_id, transcript_id, owner_id, requested_operations) -> bool:
        return (
            record.meeting_id == meeting_id
            and record.transcript_id == transcript_id
            and record.owner_id == owner_id
            and list(record.requested_operations) == list(requested_operations)
        )


class PostgresJobLifecycle:
    """Worker-side session adapter; each lifecycle action owns one transaction."""

    def __init__(self, settings) -> None:
        engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            echo=settings.database_echo,
            poolclass=NullPool,
        )
        self._engine = engine
        self._sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        self._options = {
            "max_attempts": getattr(settings, "processing_job_max_attempts", 3),
            "retry_base_seconds": getattr(settings, "processing_job_retry_base_seconds", 2.0),
            "retry_max_seconds": getattr(settings, "processing_job_retry_max_seconds", 60.0),
            "lease_seconds": getattr(settings, "processing_job_lease_seconds", 960),
        }

    async def _invoke(self, method: str, *args, **kwargs):
        async with self._sessions() as session:
            service = ProcessingJobService(session, ProcessingJobRepository(session), **self._options)
            return await getattr(service, method)(*args, **kwargs)

    async def claim(self, **kwargs) -> ClaimResult:
        return await self._invoke("claim", **kwargs)

    async def validate_registered(self, **kwargs) -> ClaimResult:
        async with self._sessions() as session:
            service = ProcessingJobService(session, ProcessingJobRepository(session), **self._options)
            return await service.validate_registered(**kwargs)

    async def reject_before_claim(self, **kwargs) -> bool:
        return await self._invoke("reject_before_claim", **kwargs)

    async def register(
        self,
        *,
        job_id: UUID,
        meeting_id: UUID,
        transcript_id: UUID,
        owner_id: UUID,
        requested_operations: list[str],
    ) -> ProcessingJobRecord:
        return await self._invoke(
            "register",
            job_id=job_id,
            meeting_id=meeting_id,
            transcript_id=transcript_id,
            owner_id=owner_id,
            requested_operations=requested_operations,
        )

    async def complete(self, *args, **kwargs) -> bool:
        return await self._invoke("complete", *args, **kwargs)

    async def fail(self, *args, **kwargs) -> FailureResult:
        return await self._invoke("fail", *args, **kwargs)

    async def aclose(self) -> None:
        await self._engine.dispose()


__all__ = ["JobStatus", "VALID_TRANSITIONS", "FailureCategory", "LifecycleIdentityError", "JobTargetRejectedError", "ClaimResult", "FailureResult", "ProcessingJobService", "PostgresJobLifecycle"]

