"""Unit contract tests for transactional outbox event claiming."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.dialects import postgresql

import sys

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))
from meeting_service_test_support import prepare_meeting_service_imports


def setUpModule() -> None:
    prepare_meeting_service_imports()
    global JobOutboxRepository
    from app.repositories.job_outbox_repository import JobOutboxRepository


class _Result:
    def __init__(self, event):
        self._event = event

    def scalar_one_or_none(self):
        return self._event


class _ImmediateSession:
    def __init__(self, event=None, result_value=...):
        self.event = event
        self.result_value = event if result_value is ... else result_value
        self.statement = None
        self.flush_calls = 0
        self.commit_calls = 0

    async def execute(self, statement):
        self.statement = statement
        return _Result(self.result_value)

    async def flush(self):
        self.flush_calls += 1

    async def commit(self):
        self.commit_calls += 1


def _drive_immediate(coroutine):
    """Run fake-only coroutines without starting a platform event loop."""
    try:
        return coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("The repository unexpectedly suspended on external I/O.")


class JobOutboxRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
        self.lease_until = self.now + timedelta(minutes=2)
        self.token = uuid4()

    def _repo(self, event):
        session = _ImmediateSession(event)
        return session, JobOutboxRepository(session)

    def _claim(self, repository):
        return _drive_immediate(
            repository.claim_next(
                now=self.now,
                lease_token=self.token,
                locked_until=self.lease_until,
            )
        )

    def test_eligible_pending_event_gets_lease_and_is_flushed_without_commit(self) -> None:
        event = SimpleNamespace(
            status="pending", available_at=self.now, lock_token=None, locked_until=None,
            attempt_count=0, ambiguity_recovery_count=0, last_error_category=None,
        )
        session, repository = self._repo(event)

        claimed = self._claim(repository)

        self.assertIs(claimed, event)
        self.assertEqual((event.lock_token, event.locked_until), (self.token, self.lease_until))
        self.assertEqual(event.attempt_count, 1)
        self.assertEqual(event.last_error_category, "publication_outcome_unknown")
        self.assertEqual(event.ambiguity_recovery_count, 0)
        self.assertEqual(session.flush_calls, 1)
        self.assertEqual(session.commit_calls, 0)
        statement = str(session.statement.compile(dialect=postgresql.dialect()))
        self.assertIn("FOR UPDATE SKIP LOCKED", statement)
        self.assertIn("job_outbox_events.status =", statement)
        self.assertIn("job_outbox_events.available_at <=", statement)
        self.assertIn("job_outbox_events.locked_until", statement)
        self.assertIn("job_outbox_events.attempt_count <", statement)

    def test_no_eligible_event_returns_none_without_mutation_or_commit(self) -> None:
        session, repository = self._repo(None)

        self.assertIsNone(self._claim(repository))

        self.assertEqual(session.flush_calls, 0)
        self.assertEqual(session.commit_calls, 0)

    def test_direct_claim_and_failure_calls_cannot_exceed_approved_policy(self) -> None:
        from shared.jobs.outbox_policy import OutboxFailureCategory

        session, repository = self._repo(None)
        with self.assertRaises(ValueError):
            _drive_immediate(repository.claim_next(
                now=self.now,
                lease_token=self.token,
                locked_until=self.lease_until,
                max_attempts=4,
            ))
        for options in (
            {"max_attempts": 4, "retry_base_seconds": 2, "retry_max_seconds": 60},
            {"max_attempts": 3, "retry_base_seconds": 2.01, "retry_max_seconds": 60},
            {"max_attempts": 3, "retry_base_seconds": 2, "retry_max_seconds": 60.01},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                _drive_immediate(repository.record_failure(
                    uuid4(),
                    self.token,
                    category=OutboxFailureCategory.BROKER_UNAVAILABLE,
                    failed_at=self.now,
                    **options,
                ))
        self.assertEqual(session.commit_calls, 0)

    def test_one_ambiguity_recovery_claim_is_separate_from_ordinary_attempts(self) -> None:
        event = SimpleNamespace(
            id=uuid4(), job_id=uuid4(), status="pending", available_at=self.now,
            lock_token=None, locked_until=None, attempt_count=3,
            ambiguity_recovery_count=0,
            last_error_category="publication_outcome_unknown",
        )
        session, repository = self._repo(event)
        claimed = _drive_immediate(repository.claim_ambiguous_recovery(
            now=self.now,
            lease_token=self.token,
            locked_until=self.lease_until,
            max_ambiguity_claims=1,
        ))
        self.assertIs(claimed, event)
        self.assertEqual(event.attempt_count, 3)
        self.assertEqual(event.ambiguity_recovery_count, 1)
        self.assertEqual(event.last_error_category, "publication_outcome_unknown")
        self.assertEqual((event.lock_token, event.locked_until), (self.token, self.lease_until))
        self.assertEqual(session.commit_calls, 0)
        sql = str(session.statement.compile(dialect=postgresql.dialect()))
        self.assertIn("FOR UPDATE SKIP LOCKED", sql)
        self.assertIn("ambiguity_recovery_count", sql)

        spent_session = _ImmediateSession(event, result_value=None)
        spent_repo = JobOutboxRepository(spent_session)
        second = _drive_immediate(spent_repo.claim_ambiguous_recovery(
            now=self.now,
            lease_token=uuid4(),
            locked_until=self.lease_until,
            max_ambiguity_claims=1,
        ))
        self.assertIsNone(second)
        spent_sql = str(spent_session.statement.compile(dialect=postgresql.dialect()))
        self.assertIn("ambiguity_recovery_count <", spent_sql)

    def test_ambiguous_outcome_releases_live_lease_and_exhausts_after_recovery(self) -> None:
        event = SimpleNamespace(
            id=uuid4(), status="pending", lock_token=self.token,
            locked_until=self.lease_until, attempt_count=3,
            ambiguity_recovery_count=0, available_at=self.now,
        )
        session, repository = self._repo(event)
        recorded = _drive_immediate(repository.record_ambiguous_outcome(
            event.id,
            self.token,
            failed_at=self.now,
            max_ambiguity_claims=1,
        ))
        self.assertTrue(recorded)
        self.assertEqual(event.last_error_category, "publication_outcome_unknown")
        self.assertIsNone(event.lock_token)
        self.assertIsNone(event.locked_until)
        self.assertEqual(session.commit_calls, 0)

        event.lock_token = self.token
        event.locked_until = self.lease_until
        event.ambiguity_recovery_count = 1
        recorded_again = _drive_immediate(repository.record_ambiguous_outcome(
            event.id,
            self.token,
            failed_at=self.now,
            max_ambiguity_claims=1,
        ))
        self.assertTrue(recorded_again)
        self.assertEqual(event.last_error_category, "ambiguous_recovery_exhausted")
        self.assertIsNone(event.lock_token)

    def test_ambiguity_allowance_cannot_be_configured_above_one(self) -> None:
        session, repository = self._repo(None)
        with self.assertRaises(ValueError):
            _drive_immediate(repository.claim_ambiguous_recovery(
                now=self.now,
                lease_token=self.token,
                locked_until=self.lease_until,
                max_ambiguity_claims=2,
            ))
        self.assertEqual(session.flush_calls, 0)

    def test_ambiguity_recovery_exhaustion_is_operator_visible_and_not_claimable(self) -> None:
        from shared.jobs.outbox_policy import OutboxFailureCategory

        event = SimpleNamespace(
            id=uuid4(), status="pending", available_at=self.now,
            lock_token=self.token, locked_until=self.now, attempt_count=3,
            ambiguity_recovery_count=1,
            last_error_category=OutboxFailureCategory.PUBLICATION_OUTCOME_UNKNOWN.value,
        )
        session, repository = self._repo(event)
        exhausted = _drive_immediate(repository.mark_ambiguous_exhausted(
            now=self.now, max_ambiguity_claims=1
        ))
        self.assertIs(exhausted, event)
        self.assertEqual(event.last_error_category, "ambiguous_recovery_exhausted")
        self.assertIsNone(event.lock_token)
        self.assertIsNone(event.locked_until)
        self.assertEqual(session.commit_calls, 0)

    def test_transient_failure_records_bounded_backoff_and_releases_current_lease(self) -> None:
        from shared.jobs.outbox_policy import OutboxFailureCategory

        event = SimpleNamespace(
            id=uuid4(), status="pending", lock_token=self.token,
            locked_until=self.lease_until, attempt_count=1, available_at=self.now,
        )
        session = _ImmediateSession(event)
        repository = JobOutboxRepository(session)

        recorded = _drive_immediate(repository.record_failure(
            event.id, self.token, category=OutboxFailureCategory.BROKER_UNAVAILABLE,
            failed_at=self.now, max_attempts=3, retry_base_seconds=2,
            retry_max_seconds=60,
        ))

        self.assertTrue(recorded)
        self.assertEqual(event.last_error_category, "broker_unavailable")
        self.assertEqual(event.available_at, self.now + timedelta(seconds=2))
        self.assertIsNone(event.lock_token)
        self.assertIsNone(event.locked_until)
        self.assertEqual(session.commit_calls, 0)

    def test_permanent_failure_is_recorded_and_not_eligible_for_reclaim(self) -> None:
        from shared.jobs.outbox_policy import OutboxFailureCategory

        event = SimpleNamespace(
            id=uuid4(), status="pending", lock_token=self.token,
            locked_until=self.lease_until, attempt_count=1, available_at=self.now,
        )
        session = _ImmediateSession(event)
        repository = JobOutboxRepository(session)
        recorded = _drive_immediate(repository.record_failure(
            event.id, self.token, category=OutboxFailureCategory.AUTHENTICATION_REJECTED,
            failed_at=self.now, max_attempts=3, retry_base_seconds=2,
            retry_max_seconds=60,
        ))

        self.assertTrue(recorded)
        self.assertEqual(event.last_error_category, "authentication_rejected")
        self.assertEqual(event.last_error_message, "Publication authentication was rejected.")
        self.assertIsNone(event.lock_token)
        self.assertIsNone(event.locked_until)

        no_work_session = _ImmediateSession(None)
        no_work_repo = JobOutboxRepository(no_work_session)
        self.assertIsNone(self._claim(no_work_repo))
        statement = str(no_work_session.statement.compile(dialect=postgresql.dialect()))
        self.assertIn("last_error_category", statement)

    def test_final_attempt_failure_and_expired_final_lease_become_exhausted(self) -> None:
        from shared.jobs.outbox_policy import OutboxFailureCategory

        event = SimpleNamespace(
            id=uuid4(), status="pending", lock_token=self.token,
            locked_until=self.lease_until, attempt_count=3, available_at=self.now,
        )
        session = _ImmediateSession(event)
        repository = JobOutboxRepository(session)
        recorded = _drive_immediate(repository.record_failure(
            event.id, self.token, category=OutboxFailureCategory.TRANSPORT_UNAVAILABLE,
            failed_at=self.now, max_attempts=3, retry_base_seconds=2,
            retry_max_seconds=60,
        ))

        self.assertTrue(recorded)
        self.assertEqual(event.last_error_category, "attempts_exhausted")
        self.assertIsNone(event.lock_token)

        crashed = SimpleNamespace(
            id=uuid4(), status="pending", lock_token=self.token,
            locked_until=self.now, attempt_count=3, available_at=self.now,
            last_error_category="broker_unavailable", last_error_message="old safe error",
        )
        crash_session = _ImmediateSession(crashed)
        exhausted = _drive_immediate(
            JobOutboxRepository(crash_session).mark_expired_exhausted(
                now=self.now, max_attempts=3
            )
        )
        self.assertIs(exhausted, crashed)
        self.assertEqual(crashed.last_error_category, "attempts_exhausted")
        self.assertEqual(crashed.last_error_message, "Publication attempts were exhausted.")
        self.assertIsNone(crashed.lock_token)
        self.assertIsNone(crashed.locked_until)

    def test_stale_token_cannot_record_failure(self) -> None:
        from shared.jobs.outbox_policy import OutboxFailureCategory

        session = _ImmediateSession(result_value=None)
        repository = JobOutboxRepository(session)
        recorded = _drive_immediate(repository.record_failure(
            uuid4(), self.token, category=OutboxFailureCategory.BROKER_UNAVAILABLE,
            failed_at=self.now, max_attempts=3, retry_base_seconds=2,
            retry_max_seconds=60,
        ))
        self.assertFalse(recorded)
        self.assertEqual(session.commit_calls, 0)
        statement = str(session.statement.compile(dialect=postgresql.dialect()))
        self.assertIn("FOR UPDATE", statement)

    def test_expired_lease_cannot_record_failure(self) -> None:
        from shared.jobs.outbox_policy import OutboxFailureCategory

        session = _ImmediateSession(result_value=None)
        repository = JobOutboxRepository(session)
        recorded = _drive_immediate(repository.record_failure(
            uuid4(), self.token, category=OutboxFailureCategory.BROKER_UNAVAILABLE,
            failed_at=self.now, max_attempts=3, retry_base_seconds=2,
            retry_max_seconds=60,
        ))
        self.assertFalse(recorded)
        statement = str(session.statement.compile(dialect=postgresql.dialect()))
        self.assertIn("job_outbox_events.locked_until >", statement)

        ambiguous_session = _ImmediateSession(result_value=None)
        ambiguous_repo = JobOutboxRepository(ambiguous_session)
        ambiguous = _drive_immediate(ambiguous_repo.record_ambiguous_outcome(
            uuid4(), self.token, failed_at=self.now, max_ambiguity_claims=1
        ))
        self.assertFalse(ambiguous)
        ambiguous_sql = str(ambiguous_session.statement.compile(dialect=postgresql.dialect()))
        self.assertIn("job_outbox_events.locked_until >", ambiguous_sql)

    def test_acknowledgment_requires_current_lease_and_does_not_commit(self) -> None:
        event_id = uuid4()
        session = _ImmediateSession(result_value=event_id)
        repository = JobOutboxRepository(session)

        acknowledged = _drive_immediate(
            repository.acknowledge_published(
                event_id,
                self.token,
                published_at=self.now,
            )
        )

        self.assertTrue(acknowledged)
        statement = str(session.statement.compile(dialect=postgresql.dialect()))
        self.assertIn("job_outbox_events.lock_token =", statement)
        self.assertIn("job_outbox_events.locked_until >", statement)
        values = {column.name: value.value for column, value in session.statement._values.items()}
        self.assertEqual(values["status"], "published")
        self.assertIsNone(values["lock_token"])
        self.assertIsNone(values["locked_until"])
        self.assertEqual(values["published_at"], self.now)
        self.assertEqual(session.flush_calls, 0)
        self.assertEqual(session.commit_calls, 0)

    def test_stale_acknowledgment_token_returns_false(self) -> None:
        session = _ImmediateSession(result_value=None)
        repository = JobOutboxRepository(session)

        acknowledged = _drive_immediate(
            repository.acknowledge_published(
                uuid4(),
                self.token,
                published_at=self.now,
            )
        )

        self.assertFalse(acknowledged)
        statement = str(session.statement.compile(dialect=postgresql.dialect()))
        self.assertIn("job_outbox_events.lock_token =", statement)
        self.assertIn("job_outbox_events.locked_until >", statement)
        self.assertEqual(session.commit_calls, 0)


if __name__ == "__main__":
    unittest.main()
