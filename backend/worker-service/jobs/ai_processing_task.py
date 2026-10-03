"""Celery task entrypoint; verifies identity then delegates to Phase 8 executor."""

from __future__ import annotations

import asyncio
import json
import logging
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
from shared.jobs.lifecycle import (
    FailureCategory,
    JobStatus,
    JobTargetRejectedError,
    LifecycleIdentityError,
)

logger = logging.getLogger("worker.ai_processing")


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


def is_job_execution_configured() -> bool:
    """Whether this process has a trusted worker runtime installed."""
    return _execution_runtime is not None


def get_job_execution_runtime() -> JobExecutionRuntime | None:
    return _execution_runtime


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
        logger.warning(
            "ai_job_authorization_rejected",
            extra={
                "event": "ai_job_authorization_rejected",
                "job_id": str(envelope.job_id),
                "meeting_id": str(envelope.meeting_id),
                "failure_category": "authorization_invalid",
            },
        )
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

    lifecycle = getattr(runtime, "lifecycle", None)
    if lifecycle is not None:
        return asyncio.run(_execute_with_lifecycle(runtime, envelope, job, user_id))

    logger.info("ai_job_execution_started", extra={"event": "ai_job_execution_started", "job_id": str(envelope.job_id), "meeting_id": str(envelope.meeting_id)})
    try:
        result = asyncio.run(runtime.executor.execute(job))
    except Exception:
        logger.error(
            "ai_job_execution_failed",
            extra={
                "event": "ai_job_execution_failed",
                "job_id": str(envelope.job_id),
                "meeting_id": str(envelope.meeting_id),
                "failure_category": "worker_execution_error",
            },
        )
        raise RuntimeError("The AI processing job could not be executed.") from None
    status = result.status.value
    failure = getattr(result, "failure", None)
    failure_code = getattr(getattr(failure, "code", None), "value", None)
    logger.info(
        "ai_job_execution_finished",
        extra={
            "event": "ai_job_execution_finished",
            "job_id": str(envelope.job_id),
            "meeting_id": str(envelope.meeting_id),
            "job_status": status,
            **({"failure_category": failure_code} if failure_code else {}),
        },
    )
    return {"job_id": str(result.job_id), "status": status}


async def _execute_with_lifecycle(runtime, envelope, job, owner_id) -> dict[str, str]:
    lifecycle = runtime.lifecycle
    operations = [item.value for item in envelope.requested_operations]
    identity = dict(
        job_id=envelope.job_id,
        meeting_id=envelope.meeting_id,
        transcript_id=envelope.transcript_id,
        owner_id=owner_id,
        requested_operations=operations,
    )
    try:
        registered = await lifecycle.validate_registered(**identity)
    except LifecycleIdentityError:
        logger.warning("ai_job_lifecycle_identity_rejected", extra={"event": "ai_job_lifecycle_identity_rejected", "job_id": str(envelope.job_id), "failure_category": FailureCategory.SECURITY.value})
        raise InvalidQueueEnvelopeError("The verified job does not match its registered lifecycle.") from None

    if registered.status in {JobStatus.COMPLETED, JobStatus.PARTIAL, JobStatus.FAILED}:
        logger.info("ai_job_duplicate_terminal", extra={"event": "ai_job_duplicate_terminal", "job_id": str(envelope.job_id), "attempt": registered.attempt, "job_status": registered.status.value, "transition_outcome": "no_op"})
        return {"job_id": str(envelope.job_id), "status": registered.status.value, "outcome": "already_terminal"}

    # A valid signature is not enough to claim work: confirm the signed owner
    # still owns the meeting and transcript through MeetingService first.
    # A current running lease or future backoff needs no second target lookup.
    if registered.retry_after_seconds is None:
        authorize_target = getattr(runtime, "authorize_target", None)
        if authorize_target is None:
            raise RuntimeError("The worker target authorization boundary is not configured.")
        try:
            await authorize_target(job)
        except JobTargetRejectedError as error:
            rejected = await lifecycle.reject_before_claim(
                **identity,
                expected_status=registered.status,
                expected_lease_token=registered.lease_token,
                category=error.category,
            )
            logger.warning("ai_job_target_rejected", extra={"event": "ai_job_target_rejected", "job_id": str(envelope.job_id), "attempt": registered.attempt, "job_status": JobStatus.FAILED.value if rejected else registered.status.value, "failure_category": error.category.value, "transition_outcome": "failed_before_claim" if rejected else "claim_raced"})
            return {"job_id": str(envelope.job_id), "status": JobStatus.FAILED.value if rejected else registered.status.value, "outcome": "target_rejected" if rejected else "claim_raced"}

    try:
        claim = await lifecycle.claim(
            **identity,
        )
    except LifecycleIdentityError:
        logger.warning("ai_job_lifecycle_identity_rejected", extra={"event": "ai_job_lifecycle_identity_rejected", "job_id": str(envelope.job_id), "failure_category": FailureCategory.SECURITY.value})
        raise InvalidQueueEnvelopeError("The verified job does not match its registered lifecycle.") from None

    if claim.outcome == "terminal":
        logger.info("ai_job_duplicate_terminal", extra={"event": "ai_job_duplicate_terminal", "job_id": str(envelope.job_id), "attempt": claim.attempt, "job_status": claim.status.value, "transition_outcome": "no_op"})
        return {"job_id": str(envelope.job_id), "status": claim.status.value, "outcome": "already_terminal"}
    if claim.outcome in {"already_running", "not_due"}:
        delay = claim.retry_after_seconds or 1.0
        logger.info("ai_job_delivery_deferred", extra={"event": "ai_job_delivery_deferred", "job_id": str(envelope.job_id), "attempt": claim.attempt, "job_status": claim.status.value, "transition_outcome": claim.outcome})
        return {"job_id": str(envelope.job_id), "status": claim.status.value, "outcome": "deferred", "retry_after_seconds": str(delay)}

    logger.info("ai_job_execution_started", extra={"event": "ai_job_execution_started", "job_id": str(envelope.job_id), "meeting_id": str(envelope.meeting_id), "attempt": claim.attempt, "job_status": JobStatus.RUNNING.value, "transition_outcome": "claimed"})
    try:
        result = await runtime.executor.execute(job)
    except Exception:
        failed = await lifecycle.fail(
            envelope.job_id,
            claim.lease_token,
            category=FailureCategory.TRANSIENT_INFRASTRUCTURE,
            retryable=True,
        )
        logger.error("ai_job_execution_failed", extra={"event": "ai_job_execution_failed", "job_id": str(envelope.job_id), "attempt": failed.attempt, "job_status": failed.status.value, "failure_category": FailureCategory.TRANSIENT_INFRASTRUCTURE.value, "transition_outcome": "retry" if failed.retry else "failed"})
        if failed.retry:
            return {"job_id": str(envelope.job_id), "status": failed.status.value, "outcome": "deferred", "retry_after_seconds": str(failed.retry_after_seconds)}
        return {"job_id": str(envelope.job_id), "status": failed.status.value, "outcome": "failed"}

    status = result.status.value
    if status == "completed":
        persisted = await lifecycle.complete(envelope.job_id, claim.lease_token, status=JobStatus.COMPLETED, result=result.processing_result.model_dump(mode="json"))
        outcome = "completed"
    elif status == "partially_failed":
        persisted = await lifecycle.complete(envelope.job_id, claim.lease_token, status=JobStatus.PARTIAL, result=result.processing_result.model_dump(mode="json"))
        outcome = "partial"
    else:
        transient = _is_transient_processing_failure(result)
        failure = await lifecycle.fail(
            envelope.job_id,
            claim.lease_token,
            category=FailureCategory.TRANSIENT_INFRASTRUCTURE if transient else _failure_category(result),
            retryable=transient,
        )
        logger.warning("ai_job_execution_finished", extra={"event": "ai_job_execution_finished", "job_id": str(envelope.job_id), "attempt": failure.attempt, "job_status": failure.status.value, "failure_category": FailureCategory.TRANSIENT_INFRASTRUCTURE.value if transient else _failure_category(result).value, "transition_outcome": "retry" if failure.retry else "failed"})
        if failure.retry:
            return {"job_id": str(envelope.job_id), "status": failure.status.value, "outcome": "deferred", "retry_after_seconds": str(failure.retry_after_seconds)}
        return {"job_id": str(envelope.job_id), "status": failure.status.value, "outcome": "failed"}

    logger.info("ai_job_execution_finished", extra={"event": "ai_job_execution_finished", "job_id": str(envelope.job_id), "attempt": claim.attempt, "job_status": status, "transition_outcome": outcome if persisted else "stale_attempt"})
    return {"job_id": str(envelope.job_id), "status": status, "outcome": outcome if persisted else "stale_attempt"}


def _is_transient_processing_failure(result: Any) -> bool:
    job_failure_code = getattr(getattr(getattr(result, "failure", None), "code", None), "value", None)
    if job_failure_code == "execution_failed":
        return True
    processing_result = getattr(result, "processing_result", None)
    if processing_result is None or processing_result.status.value != "failed":
        return False
    errors = [item.error.code.value for item in processing_result.results if item.error is not None]
    return bool(errors) and all(code in {"provider_unavailable", "provider_timeout"} for code in errors)


def _failure_category(result: Any) -> FailureCategory:
    failure = getattr(result, "failure", None)
    code = getattr(getattr(failure, "code", None), "value", "")
    if code in {"invalid_input", "transcript_not_found", "transcript_unavailable", "execution_context_required"}:
        return FailureCategory.PERMANENT_VALIDATION
    return FailureCategory.APPLICATION_PROCESSING


@celery_app.task(
    name="mannerai.process_ai_job",
    ignore_result=True,
    serializer="json",
    bind=True,
)
def process_ai_job(task, payload: object) -> dict[str, str]:
    """Celery adapter only: validation and delegation, with no AI logic."""
    result = execute_job_envelope(payload)
    if result.get("outcome") == "deferred":
        # The database claim/attempt counter is authoritative. Celery's retry
        # counter is only a scheduling mechanism and never grants attempts.
        raise task.retry(countdown=float(result["retry_after_seconds"]), max_retries=None)
    return result


__all__ = [
    "InvalidQueueEnvelopeError",
    "TrustedExecutionContextUnavailable",
    "JobExecutionRuntime",
    "configure_job_execution",
    "is_job_execution_configured",
    "execute_job_envelope",
    "process_ai_job",
]
