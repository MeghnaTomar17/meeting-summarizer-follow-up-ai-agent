"""Framework-neutral AI job contracts and process-local execution adapters.

The in-process submission adapter is a development/test boundary only. It has
no durable storage, distributed delivery, retry, or exactly-once guarantees.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.contracts import ProcessingOperation, ProcessingRequest, ProcessingStatus
from app.processing_results import (
    AIProcessingResult,
    ProcessingErrorCode,
    ProcessingFailure,
)
from app.processing_service import AIProcessingService
from shared.security.execution_context import TrustedExecutionContext
from shared.schemas.transcript import TranscriptInDB


class AIProcessingJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIALLY_FAILED = "partially_failed"
    FAILED = "failed"


class JobFailureCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    TRANSCRIPT_NOT_FOUND = "transcript_not_found"
    TRANSCRIPT_UNAVAILABLE = "transcript_unavailable"
    EXECUTION_CONTEXT_REQUIRED = "execution_context_required"
    AI_PROCESSING_FAILED = "ai_processing_failed"
    DOMAIN_MAPPING_FAILED = "domain_mapping_failed"
    EXECUTION_FAILED = "execution_failed"


_SAFE_FAILURE_MESSAGES = {
    JobFailureCode.INVALID_INPUT: "The processing job input is invalid.",
    JobFailureCode.TRANSCRIPT_NOT_FOUND: "The requested transcript is unavailable.",
    JobFailureCode.TRANSCRIPT_UNAVAILABLE: "The requested transcript is unavailable.",
    JobFailureCode.EXECUTION_CONTEXT_REQUIRED: "An authenticated execution context is required.",
    JobFailureCode.AI_PROCESSING_FAILED: "AI processing failed for all requested operations.",
    JobFailureCode.DOMAIN_MAPPING_FAILED: "AI results could not be mapped to domain inputs.",
    JobFailureCode.EXECUTION_FAILED: "The processing job could not be executed.",
}


class JobFailure(BaseModel):
    """Sanitized job-level failure; exception details are never copied here."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    code: JobFailureCode
    message: str = Field(min_length=1)

    @classmethod
    def for_code(cls, code: JobFailureCode) -> "JobFailure":
        return cls(code=code, message=_SAFE_FAILURE_MESSAGES[code])


class AIProcessingJob(BaseModel):
    """Transport-neutral job input plus its in-memory lifecycle snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: UUID = Field(default_factory=uuid4)
    meeting_id: UUID
    transcript_id: UUID
    requested_operations: list[ProcessingOperation] = Field(min_length=1)
    execution_context: TrustedExecutionContext | None = None
    execution_context_id: UUID | None = None
    execution_principal_id: UUID | None = None
    context: dict[str, str] | None = None
    status: AIProcessingJobStatus = AIProcessingJobStatus.QUEUED
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    processing_result: AIProcessingResult | None = None
    failure: JobFailure | None = None

    @field_validator("requested_operations")
    @classmethod
    def deduplicate_operations_preserving_order(
        cls, operations: list[ProcessingOperation]
    ) -> list[ProcessingOperation]:
        return list(dict.fromkeys(operations))

    @field_validator("created_at", "started_at", "completed_at")
    @classmethod
    def require_timezone_aware_timestamp(
        cls, value: datetime | None
    ) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Job timestamps must be timezone-aware.")
        return value

    @model_validator(mode="after")
    def validate_lifecycle_snapshot(self) -> "AIProcessingJob":
        if self.execution_context is None:
            if self.execution_context_id is not None or self.execution_principal_id is not None:
                raise ValueError("An execution-context binding requires a context.")
        else:
            if not self.execution_context.was_issued_by_authenticated_boundary:
                raise ValueError("Execution context must come from the authenticated boundary.")
            if (
                self.execution_context_id != self.execution_context.context_id
                or self.execution_principal_id != self.execution_context.user_id
            ):
                raise ValueError("The execution context does not match its job binding.")

        if self.started_at is not None and self.started_at < self.created_at:
            raise ValueError("Job start time cannot precede creation time.")
        if self.completed_at is not None and (
            self.started_at is not None and self.completed_at < self.started_at
        ):
            raise ValueError("Job completion time cannot precede start time.")

        if self.status == AIProcessingJobStatus.QUEUED:
            if any((self.started_at, self.completed_at, self.processing_result, self.failure)):
                raise ValueError("Queued jobs cannot contain execution results.")
        elif self.status == AIProcessingJobStatus.RUNNING:
            if self.started_at is None or any(
                (self.completed_at, self.processing_result, self.failure)
            ):
                raise ValueError("Running jobs require a start time and no terminal data.")
        elif self.status in (
            AIProcessingJobStatus.COMPLETED,
            AIProcessingJobStatus.PARTIALLY_FAILED,
        ):
            expected = (
                ProcessingStatus.COMPLETED
                if self.status == AIProcessingJobStatus.COMPLETED
                else ProcessingStatus.PARTIALLY_FAILED
            )
            if (
                self.started_at is None
                or self.completed_at is None
                or self.processing_result is None
                or self.processing_result.status != expected
                or self.failure is not None
            ):
                raise ValueError("Successful terminal jobs require a matching processing result.")
        elif self.status == AIProcessingJobStatus.FAILED:
            if self.completed_at is None or self.failure is None:
                raise ValueError("Failed jobs require a completion time and safe failure.")
            if self.processing_result is not None and (
                self.processing_result.status != ProcessingStatus.FAILED
                or self.started_at is None
            ):
                raise ValueError("Failed job processing results must represent total failure.")
        return self

    @classmethod
    def from_authenticated_context(
        cls,
        *,
        job_id: UUID | None = None,
        meeting_id: UUID,
        transcript_id: UUID,
        requested_operations: list[ProcessingOperation],
        execution_context: TrustedExecutionContext,
        context: dict[str, str] | None = None,
        created_at: datetime | None = None,
    ) -> "AIProcessingJob":
        """Build an executable job from a context issued by Gateway auth."""
        if (
            not isinstance(execution_context, TrustedExecutionContext)
            or not execution_context.was_issued_by_authenticated_boundary
        ):
            raise TypeError("A trusted execution context is required.")
        return cls(
            **({"job_id": job_id} if job_id is not None else {}),
            meeting_id=meeting_id,
            transcript_id=transcript_id,
            requested_operations=requested_operations,
            execution_context=execution_context,
            execution_context_id=execution_context.context_id,
            execution_principal_id=execution_context.user_id,
            context=context,
            **({"created_at": created_at} if created_at is not None else {}),
        )

    def start(self, *, at: datetime | None = None) -> "AIProcessingJob":
        if self.status != AIProcessingJobStatus.QUEUED:
            raise InvalidJobTransitionError("Only queued jobs can start.")
        started_at = at or datetime.now(timezone.utc)
        return self._copy_with(
            status=AIProcessingJobStatus.RUNNING,
            started_at=started_at,
        )

    def finish(
        self,
        result: AIProcessingResult,
        *,
        at: datetime | None = None,
    ) -> "AIProcessingJob":
        if self.status != AIProcessingJobStatus.RUNNING:
            raise InvalidJobTransitionError("Only running jobs can finish with a result.")
        if (
            result.meeting_id != self.meeting_id
            or result.transcript_id != self.transcript_id
            or result.requested_operations != self.requested_operations
        ):
            raise InvalidJobTransitionError("Processing result identity does not match the job.")

        terminal_at = at or datetime.now(timezone.utc)
        if result.status == ProcessingStatus.COMPLETED:
            return self._copy_with(
                status=AIProcessingJobStatus.COMPLETED,
                completed_at=terminal_at,
                processing_result=result,
            )
        if result.status == ProcessingStatus.PARTIALLY_FAILED:
            return self._copy_with(
                status=AIProcessingJobStatus.PARTIALLY_FAILED,
                completed_at=terminal_at,
                processing_result=result,
            )

        error_codes = {
            item.error.code
            for item in result.results
            if item.error is not None
        }
        if error_codes == {ProcessingErrorCode.INVALID_INPUT}:
            failure_code = JobFailureCode.INVALID_INPUT
        elif error_codes == {ProcessingErrorCode.DOMAIN_MAPPING_FAILED}:
            failure_code = JobFailureCode.DOMAIN_MAPPING_FAILED
        else:
            failure_code = JobFailureCode.AI_PROCESSING_FAILED
        return self._copy_with(
            status=AIProcessingJobStatus.FAILED,
            completed_at=terminal_at,
            processing_result=result,
            failure=JobFailure.for_code(failure_code),
        )

    def fail(
        self,
        code: JobFailureCode,
        *,
        at: datetime | None = None,
    ) -> "AIProcessingJob":
        if self.status not in (
            AIProcessingJobStatus.QUEUED,
            AIProcessingJobStatus.RUNNING,
        ):
            raise InvalidJobTransitionError("Only queued or running jobs can fail.")
        return self._copy_with(
            status=AIProcessingJobStatus.FAILED,
            completed_at=at or datetime.now(timezone.utc),
            failure=JobFailure.for_code(code),
        )

    def _copy_with(self, **updates: object) -> "AIProcessingJob":
        data = self.model_dump()
        # Keep the non-serializable issuance marker attached to the immutable
        # context object while validating lifecycle transitions.
        if self.execution_context is not None:
            data["execution_context"] = self.execution_context
        data.update(updates)
        return AIProcessingJob.model_validate(data)


class InvalidJobTransitionError(ValueError):
    """A job lifecycle transition is not allowed by the contract."""


class InvalidJobInputError(ValueError):
    """A job cannot be safely resolved to its requested transcript input."""


class InvalidExecutionContextError(ValueError):
    """The execution context does not match the context bound to the job."""


class TranscriptResolutionError(Exception):
    """Expected transcript-provider failure with no infrastructure detail."""


class TranscriptNotFoundError(TranscriptResolutionError):
    """The requested meeting or transcript does not exist or is not accessible."""


class TranscriptUnavailableError(TranscriptResolutionError):
    """The transcript exists but cannot be supplied as valid processing input."""


class NoQueuedJobError(LookupError):
    """The in-process submission adapter has no waiting job to execute."""


class TranscriptInputProvider(Protocol):
    """Resolve the requested transcript through the application/domain boundary.

    Implementations may use MeetingService and its ownership checks, but return
    only the shared transcript DTO. ORM and repository objects stay outside AI.
    """

    async def get_transcript(
        self,
        meeting_id: UUID,
        transcript_id: UUID,
        execution_context: TrustedExecutionContext,
    ) -> TranscriptInDB: ...


# Compatibility alias for the Phase 8.1 name.
TranscriptResolver = TranscriptInputProvider


class AIProcessingJobExecutor(Protocol):
    async def execute(self, job: AIProcessingJob) -> AIProcessingJob: ...


class AIProcessingJobExecutorService:
    """Resolve trusted transcript input and delegate AI work to AIProcessingService."""

    def __init__(
        self,
        processing_service: AIProcessingService,
        transcript_resolver: TranscriptInputProvider,
    ) -> None:
        self._processing_service = processing_service
        self._transcript_resolver = transcript_resolver

    async def execute(self, job: AIProcessingJob) -> AIProcessingJob:
        if (
            job.execution_context is not None
            and (
                job.execution_context_id != job.execution_context.context_id
                or job.execution_principal_id != job.execution_context.user_id
            )
        ):
            raise InvalidExecutionContextError(
                "Execution context does not match the job binding."
            )
        running = job.start()
        if job.execution_context is None:
            return running.fail(JobFailureCode.EXECUTION_CONTEXT_REQUIRED)
        try:
            transcript = await self._transcript_resolver.get_transcript(
                job.meeting_id,
                job.transcript_id,
                job.execution_context,
            )
            self._validate_transcript(job, transcript)
            request = ProcessingRequest(
                meeting_id=job.meeting_id,
                transcript_id=job.transcript_id,
                requested_operations=job.requested_operations,
                context=job.context,
            )
            result = await self._processing_service.process(request, transcript)
            if not isinstance(result, AIProcessingResult):
                raise RuntimeError("Processing service returned an invalid result.")
            if (
                result.meeting_id != job.meeting_id
                or result.transcript_id != job.transcript_id
                or result.requested_operations != job.requested_operations
            ):
                raise RuntimeError("Processing service result did not match the job.")
            return running.finish(result)
        except InvalidJobInputError:
            return running.fail(JobFailureCode.INVALID_INPUT)
        except TranscriptNotFoundError:
            return running.fail(JobFailureCode.TRANSCRIPT_NOT_FOUND)
        except TranscriptUnavailableError:
            return running.fail(JobFailureCode.TRANSCRIPT_UNAVAILABLE)
        except TranscriptResolutionError:
            return running.fail(JobFailureCode.INVALID_INPUT)
        except Exception:
            # Keep internal exceptions out of the job contract; never turn them into success.
            return running.fail(JobFailureCode.EXECUTION_FAILED)

    @staticmethod
    def _validate_transcript(
        job: AIProcessingJob,
        transcript: TranscriptInDB,
    ) -> None:
        if not isinstance(transcript, TranscriptInDB):
            raise InvalidJobInputError("Transcript resolver returned an invalid value.")
        try:
            meeting_id = UUID(transcript.meeting_id)
            transcript_id = UUID(transcript.id)
        except (TypeError, ValueError):
            raise InvalidJobInputError("Transcript identity is invalid.") from None
        if meeting_id != job.meeting_id or transcript_id != job.transcript_id:
            raise InvalidJobInputError("Transcript identity does not match the job.")


class JobSubmissionReceipt(BaseModel):
    """Acknowledgement that an in-process adapter accepted a queued job."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: UUID
    status: AIProcessingJobStatus = AIProcessingJobStatus.QUEUED
    accepted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class JobSubmissionPort(Protocol):
    async def submit(self, job: AIProcessingJob) -> JobSubmissionReceipt: ...


class InProcessJobSubmissionPort:
    """FIFO, process-local submission adapter; a future queue can replace it."""

    def __init__(self, executor: AIProcessingJobExecutor) -> None:
        self._executor = executor
        self._pending: asyncio.Queue[AIProcessingJob] = asyncio.Queue()

    async def submit(self, job: AIProcessingJob) -> JobSubmissionReceipt:
        if job.status != AIProcessingJobStatus.QUEUED:
            raise InvalidJobTransitionError("Only queued jobs can be submitted.")
        # Isolate pending state from later caller-side mutations of nested input values.
        await self._pending.put(job.model_copy(deep=True))
        return JobSubmissionReceipt(job_id=job.job_id)

    async def run_next(self) -> AIProcessingJob:
        """Execute one accepted job; intended for explicit local/test dispatch."""
        try:
            job = self._pending.get_nowait()
        except asyncio.QueueEmpty:
            raise NoQueuedJobError("There are no queued jobs.") from None
        try:
            return await self._executor.execute(job)
        finally:
            self._pending.task_done()

    @property
    def pending_count(self) -> int:
        return self._pending.qsize()


__all__ = [
    "AIProcessingJobStatus",
    "JobFailureCode",
    "JobFailure",
    "AIProcessingJob",
    "InvalidJobTransitionError",
    "InvalidJobInputError",
    "InvalidExecutionContextError",
    "TranscriptResolutionError",
    "NoQueuedJobError",
    "TranscriptInputProvider",
    "TranscriptResolver",
    "TranscriptNotFoundError",
    "TranscriptUnavailableError",
    "AIProcessingJobExecutor",
    "AIProcessingJobExecutorService",
    "JobSubmissionReceipt",
    "JobSubmissionPort",
    "InProcessJobSubmissionPort",
]
