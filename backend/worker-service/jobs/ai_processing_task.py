"""Celery task entrypoint; delegates validated work to the Phase 8 executor."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol

from pydantic import ValidationError

from shared.schemas.ai_job_envelope import AIProcessingJobEnvelope
from shared.security.execution_context import TrustedExecutionContext
from worker_queue.celery_app import celery_app


class TrustedExecutionContextUnavailable(RuntimeError):
    """No authenticated producer/worker identity resolver is configured."""


class InvalidQueueEnvelopeError(ValueError):
    """Queue payload is not a valid primitive job envelope."""


class JobExecutor(Protocol):
    async def execute(self, job: Any) -> Any: ...


class JobExecutionRuntime(Protocol):
    executor: JobExecutor

    def resolve_execution_context(
        self, envelope: AIProcessingJobEnvelope
    ) -> TrustedExecutionContext: ...

    def create_job(
        self,
        envelope: AIProcessingJobEnvelope,
        execution_context: TrustedExecutionContext,
    ) -> Any: ...


_execution_runtime: JobExecutionRuntime | None = None


def configure_job_execution(runtime: JobExecutionRuntime | None) -> None:
    """Install worker-local dependencies after trusted identity wiring exists."""
    global _execution_runtime
    _execution_runtime = runtime


def _validate_envelope(payload: object) -> AIProcessingJobEnvelope:
    try:
        wire_json = json.dumps(payload, allow_nan=False, separators=(",", ":"))
        return AIProcessingJobEnvelope.model_validate_json(wire_json)
    except (TypeError, ValueError, ValidationError):
        # Do not echo an untrusted payload (which may contain credential fields)
        # in task errors or Celery logs.
        raise InvalidQueueEnvelopeError("The queue job envelope is invalid.") from None


def execute_job_envelope(payload: object) -> dict[str, str]:
    """Validate the wire message, establish trusted context, and call executor."""
    envelope = _validate_envelope(payload)
    runtime = _execution_runtime
    if runtime is None:
        raise TrustedExecutionContextUnavailable(
            "Trusted queue identity resolution is not configured."
        )

    execution_context = runtime.resolve_execution_context(envelope)
    if (
        not isinstance(execution_context, TrustedExecutionContext)
        or not execution_context.was_issued_by_authenticated_boundary
    ):
        raise TrustedExecutionContextUnavailable(
            "The queue message has no trusted execution context."
        )

    job = runtime.create_job(envelope, execution_context)
    job_context = getattr(job, "execution_context", None)
    if (
        getattr(job, "job_id", None) != envelope.job_id
        or getattr(job, "meeting_id", None) != envelope.meeting_id
        or getattr(job, "transcript_id", None) != envelope.transcript_id
        or getattr(job, "requested_operations", None)
        != envelope.requested_operations
        or getattr(job, "execution_context_id", None)
        != execution_context.context_id
        or getattr(job, "execution_principal_id", None) != execution_context.user_id
        or not isinstance(job_context, TrustedExecutionContext)
        or not job_context.was_issued_by_authenticated_boundary
        or job_context.context_id != execution_context.context_id
        or job_context.user_id != execution_context.user_id
    ):
        raise InvalidQueueEnvelopeError("The trusted job does not match its envelope.")

    result = asyncio.run(runtime.executor.execute(job))
    return {"job_id": str(result.job_id), "status": result.status.value}


@celery_app.task(
    name="mannerai.process_ai_job",
    ignore_result=True,
    serializer="json",
)
def process_ai_job(payload: object) -> dict[str, str]:
    """Celery adapter only: validation and delegation, with no AI logic."""
    return execute_job_envelope(payload)


__all__ = [
    "InvalidQueueEnvelopeError",
    "TrustedExecutionContextUnavailable",
    "JobExecutionRuntime",
    "configure_job_execution",
    "execute_job_envelope",
    "process_ai_job",
]
