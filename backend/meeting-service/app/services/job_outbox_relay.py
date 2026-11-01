"""One-event outbox publication and acknowledgment orchestration."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.job_outbox_repository import JobOutboxRepository
from shared.database.models.job_outbox_event import JobOutboxEvent
from shared.jobs.outbox_policy import (
    MAX_OUTBOX_AMBIGUITY_RECOVERY_CLAIMS,
    MAX_OUTBOX_PUBLICATION_ATTEMPTS,
    MAX_OUTBOX_RETRY_BASE_SECONDS,
    MAX_OUTBOX_RETRY_CAP_SECONDS,
    OutboxFailureCategory,
    OutboxPublicationError,
)

logger = logging.getLogger("meeting.outbox_relay")


class OutboxEventPublisher(Protocol):
    async def publish_outbox_event(
        self,
        *,
        event_id: UUID,
        owner_id: UUID,
        job_id: UUID,
        event_type: str,
        payload: dict[str, object],
    ) -> None: ...


class OutboxLeaseLostError(RuntimeError):
    """The claimed event no longer has a live lease owned by this relay."""


class JobOutboxRelayService:
    """Publish one committed claim, then acknowledge it in a new transaction.

    Claiming must already have committed before this method is called. Broker
    publication happens outside a database transaction; acknowledgment commits
    separately and is conditional on the same, still-live lease token.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        publisher: OutboxEventPublisher,
        repository_factory: Callable[[AsyncSession], JobOutboxRepository] = JobOutboxRepository,
        clock: Callable[[], datetime] | None = None,
        max_attempts: int = MAX_OUTBOX_PUBLICATION_ATTEMPTS,
        max_ambiguity_claims: int = MAX_OUTBOX_AMBIGUITY_RECOVERY_CLAIMS,
        retry_base_seconds: float = MAX_OUTBOX_RETRY_BASE_SECONDS,
        retry_max_seconds: float = MAX_OUTBOX_RETRY_CAP_SECONDS,
    ) -> None:
        if (
            type(max_attempts) is not int
            or not 1 <= max_attempts <= MAX_OUTBOX_PUBLICATION_ATTEMPTS
            or type(max_ambiguity_claims) is not int
            or not 0 <= max_ambiguity_claims <= MAX_OUTBOX_AMBIGUITY_RECOVERY_CLAIMS
            or retry_base_seconds <= 0
            or retry_base_seconds > MAX_OUTBOX_RETRY_BASE_SECONDS
            or retry_max_seconds < retry_base_seconds
            or retry_max_seconds > MAX_OUTBOX_RETRY_CAP_SECONDS
        ):
            raise ValueError("Outbox publication retry settings are invalid.")
        self._session_factory = session_factory
        self._publisher = publisher
        self._repository_factory = repository_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._max_attempts = max_attempts
        self._max_ambiguity_claims = max_ambiguity_claims
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds

    async def publish_claimed(self, event: JobOutboxEvent) -> UUID:
        """Publish the claimed event once and commit its acknowledgment."""
        lease_token = event.lock_token
        now = self._clock()
        if (
            event.status != "pending"
            or lease_token is None
            or event.locked_until is None
            or event.locked_until <= now
            or event.last_error_category
            != OutboxFailureCategory.PUBLICATION_OUTCOME_UNKNOWN.value
        ):
            raise OutboxLeaseLostError("Outbox event does not have a current publication lease.")

        try:
            await self._publisher.publish_outbox_event(
                event_id=event.id,
                owner_id=event.owner_id,
                job_id=event.job_id,
                event_type=event.event_type,
                payload=event.payload,
            )
        except OutboxPublicationError as error:
            await self._record_publication_failure(event, lease_token, error)
            raise
        except Exception:
            # Once the publisher boundary is entered, unexpected failure does
            # not establish whether the broker accepted the message.
            error = OutboxPublicationError(
                OutboxFailureCategory.PUBLICATION_OUTCOME_UNKNOWN
            )
            await self._record_publication_failure(event, lease_token, error)
            raise error from None

        # A publisher exception exits above without acknowledgment. If broker
        # delivery succeeded but this transaction fails, the lease eventually
        # expires and the same event/job identity can be delivered again.
        async with self._session_factory() as session:
            async with session.begin():
                acknowledged = await self._repository_factory(session).acknowledge_published(
                    event.id,
                    lease_token,
                    published_at=self._clock(),
                )
                if not acknowledged:
                    raise OutboxLeaseLostError(
                        "Outbox event publication lease expired or was replaced before acknowledgment."
                    )
        return event.id

    async def _record_publication_failure(
        self,
        event: JobOutboxEvent,
        lease_token: UUID,
        error: OutboxPublicationError,
    ) -> None:
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    repository = self._repository_factory(session)
                    if error.category is OutboxFailureCategory.PUBLICATION_OUTCOME_UNKNOWN:
                        recorded = await repository.record_ambiguous_outcome(
                            event.id,
                            lease_token,
                            failed_at=self._clock(),
                            max_ambiguity_claims=self._max_ambiguity_claims,
                        )
                    else:
                        recorded = await repository.record_failure(
                            event.id,
                            lease_token,
                            category=error.category,
                            failed_at=self._clock(),
                            max_attempts=self._max_attempts,
                            retry_base_seconds=self._retry_base_seconds,
                            retry_max_seconds=self._retry_max_seconds,
                        )
            logger.log(
                logging.WARNING if recorded else logging.INFO,
                "outbox_publication_failed",
                extra={
                    "event": "outbox_publication_failed",
                    "event_id": str(event.id),
                    "job_id": str(event.job_id),
                    "attempt": event.attempt_count,
                    "failure_category": error.category.value,
                    "transition_outcome": "recorded" if recorded else "stale_lease",
                },
            )
        except Exception as state_error:
            error.add_note(
                "Recording the publication failure also failed "
                f"({type(state_error).__name__})."
            )
            logger.error(
                "outbox_failure_state_update_failed",
                extra={
                    "event": "outbox_failure_state_update_failed",
                    "event_id": str(event.id),
                    "job_id": str(event.job_id),
                    "failure_category": error.category.value,
                    "error_type": type(state_error).__name__,
                },
            )


__all__ = ["OutboxEventPublisher", "OutboxLeaseLostError", "JobOutboxRelayService"]
