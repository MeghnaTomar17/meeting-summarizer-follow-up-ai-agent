"""Authenticated internal cross-meeting answer endpoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from fastapi import APIRouter, Depends, status

from app.auth import get_authenticated_outbox_publisher, get_authenticated_user_id
from app.config.settings import AISettings, get_settings
from app.celery_submission import (
    CeleryJobSubmissionPort,
    CelerySubmissionError,
    UnsupportedQueueJobError,
)
from app.cross_meeting_answers import CrossMeetingAnswerService
from llm.provider_factory import create_model_provider
from shared.schemas.cross_meeting import (
    CrossMeetingAnswerGenerationRequest,
    CrossMeetingQuestionResponse,
)
from shared.exceptions.common import BadRequestError, ServiceUnavailableError
from shared.jobs.outbox_policy import (
    OutboxFailureCategory,
    OutboxPublicationError,
)
from shared.schemas.outbox_publication import (
    OutboxPublicationRequest,
    OutboxPublicationResponse,
)

router = APIRouter(prefix="/internal/intelligence", tags=["internal-intelligence"])
outbox_router = APIRouter(prefix="/internal/jobs", tags=["internal-job-publication"])


def get_celery_task_sender(settings: AISettings = Depends(get_settings)):
    """Create the AI-owned Celery producer without connecting at import time."""
    from celery import Celery

    sender = Celery("mannerai-ai-outbox-publisher", broker=str(settings.celery_broker_url), backend=None)
    sender.conf.update(
        task_serializer="json",
        accept_content=["json"],
        broker_connection_timeout=settings.celery_broker_connection_timeout,
        broker_transport_options={
            "socket_connect_timeout": settings.celery_broker_socket_connect_timeout,
            "socket_timeout": settings.celery_broker_socket_timeout,
            "retry_on_timeout": True,
        },
        task_ignore_result=True,
    )
    try:
        yield sender
    finally:
        sender.close()


def get_outbox_publication_port(
    sender=Depends(get_celery_task_sender),
    settings: AISettings = Depends(get_settings),
) -> CeleryJobSubmissionPort:
    """Use AI Service's existing signer and Celery publisher implementation."""
    try:
        return CeleryJobSubmissionPort.from_settings(sender, settings)
    except OutboxPublicationError as error:
        raise ServiceUnavailableError(
            error.category.safe_message,
            code=f"outbox_{error.category.value}",
        ) from None


async def get_answer_service(
    settings: AISettings = Depends(get_settings),
) -> AsyncIterator[CrossMeetingAnswerService]:
    provider = create_model_provider(settings)
    try:
        yield CrossMeetingAnswerService(provider)
    finally:
        await provider.aclose()


@router.post("/answers", response_model=CrossMeetingQuestionResponse)
async def answer_question(
    payload: CrossMeetingAnswerGenerationRequest,
    _user_id=Depends(get_authenticated_user_id),
    service: CrossMeetingAnswerService = Depends(get_answer_service),
) -> CrossMeetingQuestionResponse:
    try:
        return await service.answer(payload)
    except Exception:
        raise ServiceUnavailableError("The answer service is unavailable.") from None


@outbox_router.post(
    "/outbox-events",
    response_model=OutboxPublicationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def publish_outbox_event(
    payload: OutboxPublicationRequest,
    _service_id: str = Depends(get_authenticated_outbox_publisher),
    publisher: CeleryJobSubmissionPort = Depends(get_outbox_publication_port),
) -> OutboxPublicationResponse:
    """Sign and publish one persisted outbox event using AI-owned credentials."""
    try:
        await publisher.publish_outbox_event(
            event_id=payload.event_id,
            owner_id=payload.owner_id,
            job_id=payload.job_id,
            event_type=payload.event_type,
            payload=payload.payload.model_dump(mode="json"),
        )
    except UnsupportedQueueJobError:
        raise BadRequestError(
            OutboxFailureCategory.EVENT_INVALID.safe_message,
            code=f"outbox_{OutboxFailureCategory.EVENT_INVALID.value}",
        ) from None
    except CelerySubmissionError:
        raise ServiceUnavailableError(
            OutboxFailureCategory.PUBLICATION_OUTCOME_UNKNOWN.safe_message,
            code=f"outbox_{OutboxFailureCategory.PUBLICATION_OUTCOME_UNKNOWN.value}",
        ) from None
    except OutboxPublicationError as error:
        raise ServiceUnavailableError(
            error.category.safe_message,
            code=f"outbox_{error.category.value}",
        ) from None
    except Exception:
        raise ServiceUnavailableError(
            OutboxFailureCategory.PUBLICATION_OUTCOME_UNKNOWN.safe_message,
            code=f"outbox_{OutboxFailureCategory.PUBLICATION_OUTCOME_UNKNOWN.value}",
        ) from None
    return OutboxPublicationResponse(event_id=payload.event_id, job_id=payload.job_id)


__all__ = ["router", "outbox_router", "get_answer_service", "get_celery_task_sender"]
