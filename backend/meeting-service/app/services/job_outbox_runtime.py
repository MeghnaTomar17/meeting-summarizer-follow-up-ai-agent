"""One-shot composition for claiming and relaying one outbox event."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Callable, Protocol
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.job_outbox_repository import JobOutboxRepository
from shared.database.models.job_outbox_event import JobOutboxEvent
from shared.jobs.outbox_policy import (
    MAX_OUTBOX_AMBIGUITY_RECOVERY_CLAIMS,
    MAX_OUTBOX_PUBLICATION_ATTEMPTS,
)


class OneShotOutboxStatus(StrEnum):
    NO_WORK = "no_work"
    PUBLISHED = "published"
    EXHAUSTED = "exhausted"
    AMBIGUOUS_EXHAUSTED = "ambiguous_exhausted"


@dataclass(frozen=True)
class OneShotOutboxResult:
    status: OneShotOutboxStatus
    event_id: UUID | None = None


class ClaimedEventRelay(Protocol):
    async def publish_claimed(self, event: JobOutboxEvent) -> UUID: ...


class OneShotOutboxRuntime:
    """Claim and commit one row, close that session, then invoke the relay."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        relay: ClaimedEventRelay,
        repository_factory: Callable[[AsyncSession], JobOutboxRepository] = JobOutboxRepository,
        clock: Callable[[], datetime] | None = None,
        token_factory: Callable[[], UUID] = uuid4,
        max_attempts: int = MAX_OUTBOX_PUBLICATION_ATTEMPTS,
        max_ambiguity_claims: int = MAX_OUTBOX_AMBIGUITY_RECOVERY_CLAIMS,
    ) -> None:
        if (
            type(max_attempts) is not int
            or not 1 <= max_attempts <= MAX_OUTBOX_PUBLICATION_ATTEMPTS
            or type(max_ambiguity_claims) is not int
            or not 0 <= max_ambiguity_claims <= MAX_OUTBOX_AMBIGUITY_RECOVERY_CLAIMS
        ):
            raise ValueError("Outbox publication attempt limits are invalid.")
        self._session_factory = session_factory
        self._relay = relay
        self._repository_factory = repository_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._token_factory = token_factory
        self._max_attempts = max_attempts
        self._max_ambiguity_claims = max_ambiguity_claims

    async def run_once(self, *, locked_until: datetime) -> OneShotOutboxResult:
        """Publish no more than one eligible event; failures propagate unchanged."""
        now = self._clock()
        lease_token = self._token_factory()
        ambiguous_event = None
        ambiguous_exhausted = None
        exhausted_event = None
        async with self._session_factory() as session:
            async with session.begin():
                repository = self._repository_factory(session)
                ambiguous_event = await repository.claim_ambiguous_recovery(
                    now=now,
                    lease_token=lease_token,
                    locked_until=locked_until,
                    max_ambiguity_claims=self._max_ambiguity_claims,
                )
                if ambiguous_event is None:
                    ambiguous_exhausted = await repository.mark_ambiguous_exhausted(
                        now=now,
                        max_ambiguity_claims=self._max_ambiguity_claims,
                    )
                if ambiguous_event is None and ambiguous_exhausted is None:
                    exhausted_event = await repository.mark_expired_exhausted(
                        now=now,
                        max_attempts=self._max_attempts,
                    )
                event = None
                if (
                    ambiguous_event is None
                    and ambiguous_exhausted is None
                    and exhausted_event is None
                ):
                    event = await repository.claim_next(
                        now=now,
                        lease_token=lease_token,
                        locked_until=locked_until,
                        max_attempts=self._max_attempts,
                    )

        # The claim transaction has committed and its session is closed here.
        # The relay publishes outside this transaction and owns its separate
        # acknowledgment transaction.
        if exhausted_event is not None:
            return OneShotOutboxResult(
                status=OneShotOutboxStatus.EXHAUSTED,
                event_id=exhausted_event.id,
            )
        if ambiguous_exhausted is not None:
            return OneShotOutboxResult(
                status=OneShotOutboxStatus.AMBIGUOUS_EXHAUSTED,
                event_id=ambiguous_exhausted.id,
            )
        if ambiguous_event is not None:
            event = ambiguous_event
        if event is None:
            return OneShotOutboxResult(status=OneShotOutboxStatus.NO_WORK)
        published_event_id = await self._relay.publish_claimed(event)
        if published_event_id != event.id:
            raise RuntimeError("Outbox relay returned an unexpected event identity.")
        return OneShotOutboxResult(
            status=OneShotOutboxStatus.PUBLISHED,
            event_id=event.id,
        )


def create_one_shot_outbox_runtime(
    *,
    publisher=None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    settings=None,
    request_id: str | None = None,
) -> OneShotOutboxRuntime:
    """Compose the Meeting Service session factory and authenticated AI adapter.

    An explicit publisher remains injectable for tests. Runtime configuration
    uses Meeting Service's service identity and never receives the AI job key.
    """
    if session_factory is None:
        from shared.database.session import get_session_factory

        session_factory = get_session_factory()
    if session_factory is None:
        raise RuntimeError("Meeting Service database session factory is not initialized.")

    if settings is None:
        from app.config.settings import get_settings

        settings = get_settings()

    if publisher is None:
        from app.services.ai_outbox_publication_client import AIOutboxPublicationClient

        publisher = AIOutboxPublicationClient(settings, request_id=request_id)

    from app.services.job_outbox_relay import JobOutboxRelayService

    relay = JobOutboxRelayService(
        session_factory=session_factory,
        publisher=publisher,
        max_attempts=settings.outbox_publication_max_attempts,
        max_ambiguity_claims=settings.outbox_publication_max_ambiguity_recovery_claims,
        retry_base_seconds=settings.outbox_publication_retry_base_seconds,
        retry_max_seconds=settings.outbox_publication_retry_max_seconds,
    )
    return OneShotOutboxRuntime(
        session_factory=session_factory,
        relay=relay,
        max_attempts=settings.outbox_publication_max_attempts,
        max_ambiguity_claims=settings.outbox_publication_max_ambiguity_recovery_claims,
    )


__all__ = [
    "OneShotOutboxStatus",
    "OneShotOutboxResult",
    "OneShotOutboxRuntime",
    "create_one_shot_outbox_runtime",
]
