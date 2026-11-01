"""Unit tests for the one-shot outbox runtime composition."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import sys

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))
from meeting_service_test_support import prepare_meeting_service_imports


def setUpModule() -> None:
    prepare_meeting_service_imports()
    global OneShotOutboxResult, OneShotOutboxStatus, OneShotOutboxRuntime
    from app.services.job_outbox_runtime import (
        OneShotOutboxResult,
        OneShotOutboxStatus,
        OneShotOutboxRuntime,
    )


NOW = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
LOCKED_UNTIL = NOW + timedelta(minutes=2)


class _Transaction:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        self.session.events.append("transaction_started")

    async def __aexit__(self, exc_type, _exc, _tb):
        self.session.events.append("rolled_back" if exc_type else "committed")
        return False


class _Session:
    def __init__(self, events):
        self.events = events
        self.closed = False

    def begin(self):
        return _Transaction(self)


class _SessionFactory:
    def __init__(self, session):
        self.session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_args):
        self.session.closed = True
        self.session.events.append("session_closed")
        return False


class _Repository:
    def __init__(self, event, events, exhausted=None, ambiguous=None, ambiguous_exhausted=None):
        self.event = event
        self.events = events
        self.exhausted = exhausted
        self.ambiguous = ambiguous
        self.ambiguous_exhausted = ambiguous_exhausted
        self.calls = []
        self.ambiguous_calls = []

    async def claim_ambiguous_recovery(
        self, *, now, lease_token, locked_until, max_ambiguity_claims
    ):
        self.ambiguous_calls.append((now, lease_token, locked_until, max_ambiguity_claims))
        self.events.append("ambiguous_claim_called")
        if self.ambiguous is not None:
            self.ambiguous.lock_token = lease_token
            self.ambiguous.locked_until = locked_until
            self.ambiguous.ambiguity_recovery_count = 1
        return self.ambiguous

    async def mark_ambiguous_exhausted(self, *, now, max_ambiguity_claims):
        self.events.append("ambiguous_exhaustion_checked")
        return self.ambiguous_exhausted

    async def claim_next(self, *, now, lease_token, locked_until, max_attempts):
        self.calls.append((now, lease_token, locked_until))
        self.events.append("claim_called")
        if self.event is not None:
            self.event.lock_token = lease_token
            self.event.locked_until = locked_until
            self.event.last_error_category = "publication_outcome_unknown"
            self.event.ambiguity_recovery_count = 0
        return self.event

    async def mark_expired_exhausted(self, *, now, max_attempts):
        self.events.append(("exhaustion_checked", now, max_attempts))
        return self.exhausted


def _drive(coroutine):
    try:
        return coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("Mock-only runtime unexpectedly suspended on external I/O.")


class OneShotOutboxRuntimeTests(unittest.TestCase):
    def test_runtime_rejects_attempt_limits_above_approved_policy(self):
        with self.assertRaises(ValueError):
            OneShotOutboxRuntime(
                session_factory=lambda: None,
                relay=SimpleNamespace(publish_claimed=AsyncMock()),
                max_attempts=4,
            )

    def _build(self, event, exhausted=None, ambiguous=None, ambiguous_exhausted=None):
        events = []
        session = _Session(events)
        repository = _Repository(event, events, exhausted, ambiguous, ambiguous_exhausted)
        async def publish_claimed(claimed):
            events.append(("relay_called", session.closed, claimed.lock_token, claimed.locked_until))
            return claimed.id

        relay = SimpleNamespace(publish_claimed=AsyncMock(side_effect=publish_claimed))
        runtime = OneShotOutboxRuntime(
            session_factory=_SessionFactory(session),
            relay=relay,
            repository_factory=lambda _session: repository,
            clock=lambda: NOW,
            token_factory=uuid4,
        )
        return runtime, session, repository, relay, events

    def test_no_work_result_closes_session_without_calling_relay(self):
        runtime, session, repository, relay, events = self._build(None)

        result = _drive(runtime.run_once(locked_until=LOCKED_UNTIL))

        self.assertEqual(result, OneShotOutboxResult(status=OneShotOutboxStatus.NO_WORK))
        self.assertEqual(len(repository.calls), 1)
        relay.publish_claimed.assert_not_awaited()
        self.assertTrue(session.closed)
        self.assertIn("committed", events)

    def test_expired_final_claim_is_marked_exhausted_without_relaying(self):
        event = SimpleNamespace(id=uuid4())
        runtime, session, repository, relay, _events = self._build(None, exhausted=event)

        result = _drive(runtime.run_once(locked_until=LOCKED_UNTIL))

        self.assertEqual(
            result,
            OneShotOutboxResult(
                status=OneShotOutboxStatus.EXHAUSTED,
                event_id=event.id,
            ),
        )
        self.assertTrue(session.closed)
        relay.publish_claimed.assert_not_awaited()
        self.assertEqual(len(repository.calls), 0)

    def test_ambiguous_recovery_claim_is_forwarded_without_using_ordinary_claim_path(self):
        event = SimpleNamespace(id=uuid4(), status="pending", lock_token=None, locked_until=None)
        runtime, session, repository, relay, events = self._build(None, ambiguous=event)
        result = _drive(runtime.run_once(locked_until=LOCKED_UNTIL))
        self.assertEqual(result.status, OneShotOutboxStatus.PUBLISHED)
        self.assertTrue(session.closed)
        self.assertEqual(len(repository.ambiguous_calls), 1)
        self.assertEqual(len(repository.calls), 0)
        relay.publish_claimed.assert_awaited_once_with(event)
        self.assertLess(events.index("committed"), events.index("session_closed"))

    def test_exhausted_ambiguity_recovery_stops_without_ordinary_claim_or_relay(self):
        event = SimpleNamespace(id=uuid4())
        runtime, _session, repository, relay, _events = self._build(
            None, ambiguous_exhausted=event
        )
        result = _drive(runtime.run_once(locked_until=LOCKED_UNTIL))
        self.assertEqual(result.status, OneShotOutboxStatus.AMBIGUOUS_EXHAUSTED)
        self.assertEqual(result.event_id, event.id)
        self.assertEqual(len(repository.calls), 0)
        relay.publish_claimed.assert_not_awaited()

    def test_claim_commits_and_session_closes_before_relay_call(self):
        event = SimpleNamespace(id=uuid4(), status="pending", lock_token=None, locked_until=None)
        runtime, session, _repository, relay, events = self._build(event)

        result = _drive(runtime.run_once(locked_until=LOCKED_UNTIL))

        self.assertEqual(result.status, OneShotOutboxStatus.PUBLISHED)
        self.assertEqual(result.event_id, event.id)
        self.assertTrue(session.closed)
        relay.publish_claimed.assert_awaited_once_with(event)
        self.assertLess(events.index("committed"), events.index("session_closed"))
        self.assertEqual(events[-1], ("relay_called", True, event.lock_token, LOCKED_UNTIL))

    def test_claimed_lease_is_forwarded_to_existing_relay_interface(self):
        event = SimpleNamespace(id=uuid4(), status="pending", lock_token=None, locked_until=None)
        runtime, _session, _repository, relay, _events = self._build(event)

        _drive(runtime.run_once(locked_until=LOCKED_UNTIL))

        relay.publish_claimed.assert_awaited_once()
        claimed = relay.publish_claimed.await_args.args[0]
        self.assertIs(claimed, event)
        self.assertIsNotNone(claimed.lock_token)
        self.assertEqual(claimed.locked_until, LOCKED_UNTIL)

    def test_relay_failure_propagates_after_durable_claim_commit(self):
        event = SimpleNamespace(id=uuid4(), status="pending", lock_token=None, locked_until=None)
        runtime, session, _repository, relay, events = self._build(event)
        relay.publish_claimed.side_effect = RuntimeError("broker failed")

        with self.assertRaisesRegex(RuntimeError, "broker failed"):
            _drive(runtime.run_once(locked_until=LOCKED_UNTIL))

        self.assertIn("committed", events)
        self.assertTrue(session.closed)
        self.assertEqual(event.status, "pending")
        self.assertIsNotNone(event.lock_token)
        self.assertEqual(event.locked_until, LOCKED_UNTIL)

    def test_invocation_claims_at_most_one_event(self):
        event = SimpleNamespace(id=uuid4(), status="pending", lock_token=None, locked_until=None)
        runtime, _session, repository, relay, _events = self._build(event)

        result = _drive(runtime.run_once(locked_until=LOCKED_UNTIL))

        self.assertEqual(result.status, OneShotOutboxStatus.PUBLISHED)
        self.assertEqual(len(repository.calls), 1)
        relay.publish_claimed.assert_awaited_once()

    def test_session_is_closed_on_no_work_success_and_failure(self):
        for event, relay_error in (
            (None, None),
            (SimpleNamespace(id=uuid4(), status="pending", lock_token=None, locked_until=None), None),
            (SimpleNamespace(id=uuid4(), status="pending", lock_token=None, locked_until=None), RuntimeError("publish failed")),
        ):
            with self.subTest(has_event=event is not None, relay_error=relay_error is not None):
                runtime, session, _repository, relay, _events = self._build(event)
                if relay_error is not None:
                    relay.publish_claimed.side_effect = relay_error
                if relay_error:
                    with self.assertRaisesRegex(RuntimeError, "publish failed"):
                        _drive(runtime.run_once(locked_until=LOCKED_UNTIL))
                else:
                    _drive(runtime.run_once(locked_until=LOCKED_UNTIL))
                self.assertTrue(session.closed)


if __name__ == "__main__":
    unittest.main()
