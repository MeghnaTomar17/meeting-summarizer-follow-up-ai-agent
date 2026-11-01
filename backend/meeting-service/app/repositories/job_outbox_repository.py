"""Transactional claims for pending processing-job outbox events."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.models.job_outbox_event import JobOutboxEvent
from shared.jobs.outbox_policy import (
    MAX_OUTBOX_AMBIGUITY_RECOVERY_CLAIMS,
    MAX_OUTBOX_PUBLICATION_ATTEMPTS,
    MAX_OUTBOX_RETRY_BASE_SECONDS,
    MAX_OUTBOX_RETRY_CAP_SECONDS,
    OutboxFailureCategory,
    outbox_retry_delay,
)


_RETRYABLE_CATEGORIES = (
    OutboxFailureCategory.TRANSPORT_UNAVAILABLE.value,
    OutboxFailureCategory.BROKER_UNAVAILABLE.value,
)
_UNKNOWN_OUTCOME = OutboxFailureCategory.PUBLICATION_OUTCOME_UNKNOWN.value


class JobOutboxRepository:
    """Claim one eligible event while leaving transaction ownership to caller."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim_next(
        self,
        *,
        now: datetime,
        lease_token: UUID,
        locked_until: datetime,
        max_attempts: int = MAX_OUTBOX_PUBLICATION_ATTEMPTS,
    ) -> JobOutboxEvent | None:
        """Lease the oldest eligible event using PostgreSQL skip-locked semantics.

        The existing schema represents an in-progress claim with `lock_token`
        and `locked_until`; status remains `pending` until publishing is added.
        The caller commits or rolls back the surrounding transaction.
        """
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Claim time must be timezone-aware.")
        if locked_until.tzinfo is None or locked_until.utcoffset() is None:
            raise ValueError("Claim lease expiry must be timezone-aware.")
        if locked_until <= now:
            raise ValueError("Claim lease expiry must be later than claim time.")
        if (
            type(max_attempts) is not int
            or not 1 <= max_attempts <= MAX_OUTBOX_PUBLICATION_ATTEMPTS
        ):
            raise ValueError("Maximum outbox attempts must be a positive integer.")

        statement = (
            select(JobOutboxEvent)
            .where(
                JobOutboxEvent.status == "pending",
                JobOutboxEvent.available_at <= now,
                JobOutboxEvent.attempt_count < max_attempts,
                or_(
                    JobOutboxEvent.last_error_category.is_(None),
                    JobOutboxEvent.last_error_category.in_(_RETRYABLE_CATEGORIES),
                ),
                or_(
                    JobOutboxEvent.lock_token.is_(None),
                    JobOutboxEvent.locked_until <= now,
                ),
            )
            .order_by(JobOutboxEvent.created_at.asc(), JobOutboxEvent.id.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(statement)
        event = result.scalar_one_or_none()
        if event is None:
            return None

        event.lock_token = lease_token
        event.locked_until = locked_until
        event.attempt_count += 1
        event.last_error_category = _UNKNOWN_OUTCOME
        event.last_error_message = OutboxFailureCategory.PUBLICATION_OUTCOME_UNKNOWN.safe_message
        await self._session.flush()
        return event

    async def claim_ambiguous_recovery(
        self,
        *,
        now: datetime,
        lease_token: UUID,
        locked_until: datetime,
        max_ambiguity_claims: int = MAX_OUTBOX_AMBIGUITY_RECOVERY_CLAIMS,
    ) -> JobOutboxEvent | None:
        """Claim one expired/cleared unknown outcome using its separate allowance."""
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Claim time must be timezone-aware.")
        if locked_until.tzinfo is None or locked_until.utcoffset() is None or locked_until <= now:
            raise ValueError("Claim lease expiry must be later than claim time.")
        if (
            type(max_ambiguity_claims) is not int
            or not 0 <= max_ambiguity_claims <= MAX_OUTBOX_AMBIGUITY_RECOVERY_CLAIMS
        ):
            raise ValueError("Maximum ambiguity recovery claims must be zero or one.")
        if max_ambiguity_claims == 0:
            return None

        result = await self._session.execute(
            select(JobOutboxEvent)
            .where(
                JobOutboxEvent.status == "pending",
                JobOutboxEvent.last_error_category == _UNKNOWN_OUTCOME,
                JobOutboxEvent.available_at <= now,
                JobOutboxEvent.ambiguity_recovery_count < max_ambiguity_claims,
                or_(
                    JobOutboxEvent.lock_token.is_(None),
                    JobOutboxEvent.locked_until <= now,
                ),
            )
            .order_by(JobOutboxEvent.created_at.asc(), JobOutboxEvent.id.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        event = result.scalar_one_or_none()
        if event is None:
            return None
        event.lock_token = lease_token
        event.locked_until = locked_until
        event.ambiguity_recovery_count += 1
        event.last_error_message = OutboxFailureCategory.PUBLICATION_OUTCOME_UNKNOWN.safe_message
        await self._session.flush()
        return event

    async def mark_ambiguous_exhausted(
        self,
        *,
        now: datetime,
        max_ambiguity_claims: int = MAX_OUTBOX_AMBIGUITY_RECOVERY_CLAIMS,
    ) -> JobOutboxEvent | None:
        """Stop one unknown outcome after its separate recovery allowance is used."""
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Exhaustion check time must be timezone-aware.")
        if (
            type(max_ambiguity_claims) is not int
            or not 0 <= max_ambiguity_claims <= MAX_OUTBOX_AMBIGUITY_RECOVERY_CLAIMS
        ):
            raise ValueError("Maximum ambiguity recovery claims must be zero or one.")
        result = await self._session.execute(
            select(JobOutboxEvent)
            .where(
                JobOutboxEvent.status == "pending",
                JobOutboxEvent.last_error_category == _UNKNOWN_OUTCOME,
                JobOutboxEvent.available_at <= now,
                JobOutboxEvent.ambiguity_recovery_count >= max_ambiguity_claims,
                or_(
                    JobOutboxEvent.lock_token.is_(None),
                    JobOutboxEvent.locked_until <= now,
                ),
            )
            .order_by(JobOutboxEvent.created_at.asc(), JobOutboxEvent.id.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        event = result.scalar_one_or_none()
        if event is None:
            return None
        event.last_error_category = OutboxFailureCategory.AMBIGUOUS_RECOVERY_EXHAUSTED.value
        event.last_error_message = OutboxFailureCategory.AMBIGUOUS_RECOVERY_EXHAUSTED.safe_message
        event.lock_token = None
        event.locked_until = None
        await self._session.flush()
        return event

    async def record_failure(
        self,
        event_id: UUID,
        lease_token: UUID,
        *,
        category: OutboxFailureCategory,
        failed_at: datetime,
        max_attempts: int,
        retry_base_seconds: float,
        retry_max_seconds: float,
    ) -> bool:
        """Record a sanitized failure and release only the matching lease."""
        if failed_at.tzinfo is None or failed_at.utcoffset() is None:
            raise ValueError("Failure time must be timezone-aware.")
        if (
            type(max_attempts) is not int
            or not 1 <= max_attempts <= MAX_OUTBOX_PUBLICATION_ATTEMPTS
        ):
            raise ValueError("Maximum outbox attempts must be a positive integer.")
        if (
            retry_base_seconds <= 0
            or retry_base_seconds > MAX_OUTBOX_RETRY_BASE_SECONDS
            or retry_max_seconds < retry_base_seconds
            or retry_max_seconds > MAX_OUTBOX_RETRY_CAP_SECONDS
        ):
            raise ValueError("Outbox publication retry settings are invalid.")
        if not isinstance(category, OutboxFailureCategory) or category in {
            OutboxFailureCategory.ATTEMPTS_EXHAUSTED,
            OutboxFailureCategory.PUBLICATION_OUTCOME_UNKNOWN,
            OutboxFailureCategory.AMBIGUOUS_RECOVERY_EXHAUSTED,
        }:
            raise ValueError("Outbox failure category is invalid.")

        result = await self._session.execute(
            select(JobOutboxEvent)
            .where(
                JobOutboxEvent.id == event_id,
                JobOutboxEvent.status == "pending",
                JobOutboxEvent.lock_token == lease_token,
                JobOutboxEvent.locked_until > failed_at,
            )
            .with_for_update()
        )
        event = result.scalar_one_or_none()
        if event is None:
            return False

        stored_category = category
        if category.retryable and event.attempt_count >= max_attempts:
            stored_category = OutboxFailureCategory.ATTEMPTS_EXHAUSTED
        elif category.retryable:
            delay = outbox_retry_delay(
                event.attempt_count,
                base_seconds=retry_base_seconds,
                maximum_seconds=retry_max_seconds,
            )
            event.available_at = failed_at + timedelta(seconds=delay)

        event.last_error_category = stored_category.value
        event.last_error_message = stored_category.safe_message
        event.lock_token = None
        event.locked_until = None
        await self._session.flush()
        return True

    async def record_ambiguous_outcome(
        self,
        event_id: UUID,
        lease_token: UUID,
        *,
        failed_at: datetime,
        max_ambiguity_claims: int = MAX_OUTBOX_AMBIGUITY_RECOVERY_CLAIMS,
    ) -> bool:
        """Release a live lease as unknown, or stop after its recovery claim."""
        if failed_at.tzinfo is None or failed_at.utcoffset() is None:
            raise ValueError("Failure time must be timezone-aware.")
        if (
            type(max_ambiguity_claims) is not int
            or not 0 <= max_ambiguity_claims <= MAX_OUTBOX_AMBIGUITY_RECOVERY_CLAIMS
        ):
            raise ValueError("Maximum ambiguity recovery claims must be zero or one.")
        result = await self._session.execute(
            select(JobOutboxEvent)
            .where(
                JobOutboxEvent.id == event_id,
                JobOutboxEvent.status == "pending",
                JobOutboxEvent.lock_token == lease_token,
                JobOutboxEvent.locked_until > failed_at,
            )
            .with_for_update()
        )
        event = result.scalar_one_or_none()
        if event is None:
            return False
        if event.ambiguity_recovery_count >= max_ambiguity_claims:
            category = OutboxFailureCategory.AMBIGUOUS_RECOVERY_EXHAUSTED
        else:
            category = OutboxFailureCategory.PUBLICATION_OUTCOME_UNKNOWN
        event.last_error_category = category.value
        event.last_error_message = category.safe_message
        event.lock_token = None
        event.locked_until = None
        await self._session.flush()
        return True

    async def mark_expired_exhausted(
        self,
        *,
        now: datetime,
        max_attempts: int = MAX_OUTBOX_PUBLICATION_ATTEMPTS,
    ) -> JobOutboxEvent | None:
        """Make one crashed final claim explicitly operator-action-required."""
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Exhaustion check time must be timezone-aware.")
        if (
            type(max_attempts) is not int
            or not 1 <= max_attempts <= MAX_OUTBOX_PUBLICATION_ATTEMPTS
        ):
            raise ValueError("Maximum outbox attempts must be a positive integer.")
        result = await self._session.execute(
            select(JobOutboxEvent)
            .where(
                JobOutboxEvent.status == "pending",
                JobOutboxEvent.available_at <= now,
                JobOutboxEvent.attempt_count >= max_attempts,
                or_(
                    JobOutboxEvent.last_error_category.is_(None),
                    JobOutboxEvent.last_error_category.in_(_RETRYABLE_CATEGORIES),
                ),
                or_(
                    JobOutboxEvent.lock_token.is_(None),
                    JobOutboxEvent.locked_until <= now,
                ),
            )
            .order_by(JobOutboxEvent.created_at.asc(), JobOutboxEvent.id.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        event = result.scalar_one_or_none()
        if event is None:
            return None
        event.last_error_category = OutboxFailureCategory.ATTEMPTS_EXHAUSTED.value
        event.last_error_message = OutboxFailureCategory.ATTEMPTS_EXHAUSTED.safe_message
        event.lock_token = None
        event.locked_until = None
        await self._session.flush()
        return event

    async def acknowledge_published(
        self,
        event_id: UUID,
        lease_token: UUID,
        *,
        published_at: datetime,
    ) -> bool:
        """Mark an event published only while its pending lease is still owned.

        This conditional update is atomic. It flushes through the database
        statement but deliberately leaves commit/rollback to the caller.
        """
        if published_at.tzinfo is None or published_at.utcoffset() is None:
            raise ValueError("Publication acknowledgment time must be timezone-aware.")
        statement = (
            update(JobOutboxEvent)
            .where(
                JobOutboxEvent.id == event_id,
                JobOutboxEvent.status == "pending",
                JobOutboxEvent.lock_token == lease_token,
                JobOutboxEvent.locked_until > published_at,
            )
            .values(
                status="published",
                published_at=published_at,
                lock_token=None,
                locked_until=None,
                last_error_category=None,
                last_error_message=None,
            )
            .returning(JobOutboxEvent.id)
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none() is not None


__all__ = ["JobOutboxRepository"]
