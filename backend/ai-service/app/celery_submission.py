"""Celery queue adapter for the existing application job-submission port."""

from __future__ import annotations

import asyncio
import json
from typing import Protocol

from app.background_processing import (
    AIProcessingJob,
    AIProcessingJobStatus,
    InvalidJobTransitionError,
    JobSubmissionReceipt,
)
from shared.schemas.ai_job_envelope import AIProcessingJobEnvelope
from shared.jobs.outbox_policy import (
    OutboxFailureCategory,
    OutboxPublicationError,
)
from shared.security.background_job_authorization import issue_job_authorization


class UnsupportedQueueJobError(ValueError):
    """Job contains data that is not approved for the distributed envelope."""


class CelerySubmissionError(RuntimeError):
    """The broker did not acknowledge queue submission."""


class CeleryTaskPublisher(Protocol):
    def send_task(
        self,
        name: str,
        *,
        args: list[dict[str, object]],
        task_id: str,
        headers: dict[str, str] | None = None,
    ): ...


class CeleryJobSubmissionPort:
    """Publish a strict primitive envelope; never execute AI in the adapter."""

    def __init__(
        self,
        publisher: CeleryTaskPublisher,
        *,
        signing_key: str,
        issuer: str = "ai-service",
        audience: str = "mannerai-worker",
        authorization_expire_seconds: int = 120,
    ) -> None:
        self._publisher = publisher
        self._signing_key = signing_key
        self._issuer = issuer
        self._audience = audience
        self._authorization_expire_seconds = authorization_expire_seconds

    @classmethod
    def from_settings(
        cls, publisher: CeleryTaskPublisher, settings: object | None = None
    ) -> "CeleryJobSubmissionPort":
        """Create the producer port from AI service environment settings."""
        if settings is None:
            from app.config.settings import get_settings

            settings = get_settings()
        signing_key = getattr(settings, "background_job_signing_private_key", None)
        if signing_key is None:
            raise OutboxPublicationError(
                OutboxFailureCategory.CONFIGURATION_INVALID
            )
        return cls(
            publisher,
            signing_key=signing_key.get_secret_value(),
            issuer=settings.background_job_issuer,
            audience=settings.background_job_audience,
            authorization_expire_seconds=settings.background_job_authorization_expire_seconds,
        )

    async def submit(self, job: AIProcessingJob) -> JobSubmissionReceipt:
        if job.status != AIProcessingJobStatus.QUEUED:
            raise InvalidJobTransitionError("Only queued jobs can be submitted.")
        if (
            job.execution_context is None
            or not job.execution_context.was_issued_by_authenticated_boundary
            or job.execution_context_id != job.execution_context.context_id
            or job.execution_principal_id != job.execution_context.user_id
        ):
            raise InvalidJobTransitionError(
                "A job with a bound trusted execution context is required."
            )
        if job.context is not None:
            raise UnsupportedQueueJobError(
                "Free-form processing context is not supported in queue messages."
            )

        envelope = AIProcessingJobEnvelope(
            job_id=job.job_id,
            meeting_id=job.meeting_id,
            transcript_id=job.transcript_id,
            requested_operations=[operation.value for operation in job.requested_operations],
        )
        authorization = issue_job_authorization(
            envelope,
            job.execution_context.user_id,
            private_key=self._signing_key,
            issuer=self._issuer,
            audience=self._audience,
            expires_seconds=self._authorization_expire_seconds,
        )
        payload = {
            "envelope": envelope.model_dump(mode="json"),
            "authorization": authorization,
        }
        # Celery's synchronous publisher can wait for broker IO; keep that away
        # from the submitting event loop. Any broker error propagates to caller.
        try:
            result = await asyncio.to_thread(
                self._publisher.send_task,
                "mannerai.process_ai_job",
                args=[payload],
                task_id=str(job.job_id),
            )
        except Exception:
            raise CelerySubmissionError(
                "Celery broker submission failed; the job was not accepted."
            ) from None
        if getattr(result, "id", None) != str(job.job_id):
            raise OutboxPublicationError(OutboxFailureCategory.PROTOCOL_ERROR)
        return JobSubmissionReceipt(job_id=job.job_id)

    async def publish_outbox_event(
        self,
        *,
        event_id,
        owner_id,
        job_id,
        event_type: str,
        payload: dict[str, object],
    ) -> None:
        """Sign and publish the persisted outbox envelope through Celery."""
        await asyncio.to_thread(
            self._publish_outbox_event,
            event_id=event_id,
            owner_id=owner_id,
            job_id=job_id,
            event_type=event_type,
            payload=payload,
        )

    def _publish_outbox_event(
        self,
        *,
        event_id,
        owner_id,
        job_id,
        event_type: str,
        payload: dict[str, object],
    ) -> None:
        """Synchronous implementation kept off the async event loop."""
        if event_type != "ai.processing.requested.v1":
            raise UnsupportedQueueJobError("Unsupported outbox event type.")
        try:
            envelope = AIProcessingJobEnvelope.model_validate_json(
                json.dumps(payload, allow_nan=False, separators=(",", ":"))
            )
        except (TypeError, ValueError):
            raise UnsupportedQueueJobError("Outbox event payload is invalid.") from None
        if envelope.job_id != job_id:
            raise UnsupportedQueueJobError("Outbox event identity does not match its job envelope.")

        try:
            authorization = issue_job_authorization(
                envelope,
                owner_id,
                private_key=self._signing_key,
                issuer=self._issuer,
                audience=self._audience,
                expires_seconds=self._authorization_expire_seconds,
            )
        except Exception:
            raise OutboxPublicationError(
                OutboxFailureCategory.CONFIGURATION_INVALID
            ) from None
        message = {
            "envelope": envelope.model_dump(mode="json"),
            "authorization": authorization,
        }
        try:
            result = self._publisher.send_task(
                "mannerai.process_ai_job",
                args=[message],
                task_id=str(job_id),
                headers={"outbox_event_id": str(event_id)},
            )
        except Exception:
            raise CelerySubmissionError(
                "Celery broker publication failed; the outbox event was not acknowledged."
            ) from None
        if getattr(result, "id", None) != str(job_id):
            raise OutboxPublicationError(OutboxFailureCategory.PROTOCOL_ERROR)


__all__ = [
    "CeleryTaskPublisher",
    "CeleryJobSubmissionPort",
    "UnsupportedQueueJobError",
    "CelerySubmissionError",
]
