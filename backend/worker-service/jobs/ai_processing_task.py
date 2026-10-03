"""Celery task entrypoint; verifies identity then delegates to Phase 8 executor."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol
from uuid import UUID

from pydantic import ValidationError

from shared.schemas.ai_job_envelope import (
    AIProcessingJobEnvelope,
    AuthorizedAIProcessingJobMessage,
)
from shared.security.background_job_authorization import verify_job_authorization
from shared.security.execution_context import TrustedExecutionContext
from worker_queue.celery_app import celery_app


class TrustedExecutionContextUnavailable(RuntimeError):
    """No valid signed producer authorization is configured or supplied."""


class InvalidQueueEnvelopeError(ValueError):
    """Queue payload is not a valid primitive job message."""


class JobExecutor(Protocol):
    async def execute(self, job: Any) -> Any: ...


class JobExecutionRuntime(Protocol):
    executor: JobExecutor
    verification_key: str
    authorization_issuer: str
    authorization_audience: str
    authorization_max_age_seconds: int

    def create_job(
        self,
        envelope: AIProcessingJobEnvelope,
        execution_context: TrustedExecutionContext,
    ) -> Any: ...


_execution_runtime: JobExecutionRuntime | None = None


def configure_job_execution(runtime: JobExecutionRuntime | None) -> None:
    """Install worker-local verification and Phase 8 execution dependencies."""
    global _execution_runtime
    _execution_runtime = runtime


def _validate_message(payload: object) -> tuple[AIProcessingJobEnvelope, str]:
    try:
        wire_json = json.dumps(payload, allow_nan=False, separators=(",", ":"))
        message = AuthorizedAIProcessingJobMessage.model_validate_json(wire_json)
        return message.envelope, message.authorization
    except (TypeError, ValueError, ValidationError):
        # Never echo an untrusted message, which may carry credential-like data.
        raise InvalidQueueEnvelopeError("The queue job message is invalid.") from None


def execute_job_envelope(payload: object) -> dict[str, str]:
    """Validate, verify, establish context, then call the existing executor."""
    envelope, authorization = _validate_message(payload)
    runtime = _execution_runtime
    if runtime is None:
        raise TrustedExecutionContextUnavailable(
            "Trusted queue authorization is not configured."
        )

    try:
        user_id = verify_job_authorization(
            authorization,
            envelope,
            public_key=runtime.verification_key,
            issuer=runtime.authorization_issuer,
            audience=runtime.authorization_audience,
            max_age_seconds=runtime.authorization_max_age_seconds,
        )
    except Exception:
        raise TrustedExecutionContextUnavailable(
            "The queue job authorization is invalid."
        ) from None
    if not isinstance(user_id, UUID):
        raise TrustedExecutionContextUnavailable("The queue job authorization is invalid.")

    # Identity is issued only from the verified signed subject; no queue field
    # can be used to construct this context.
    execution_context = TrustedExecutionContext._issue_from_authenticated_user_id(user_id)
    job = runtime.create_job(envelope, execution_context)
    job_context = getattr(job, "execution_context", None)
    if (
        getattr(job, "job_id", None) != envelope.job_id
        or getattr(job, "meeting_id", None) != envelope.meeting_id
        or getattr(job, "transcript_id", None) != envelope.transcript_id
        or getattr(job, "requested_operations", None) != envelope.requested_operations
        or getattr(job, "execution_context_id", None) != execution_context.context_id
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
