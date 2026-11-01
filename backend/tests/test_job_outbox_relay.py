"""Unit tests for publishing and acknowledging one claimed outbox event."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import sys

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))
from meeting_service_test_support import prepare_meeting_service_imports


def setUpModule() -> None:
    prepare_meeting_service_imports()
    global JobOutboxRelayService, OutboxLeaseLostError
    from app.services.job_outbox_relay import JobOutboxRelayService, OutboxLeaseLostError


EVENT_ID = uuid4()
JOB_ID = uuid4()
OWNER_ID = uuid4()
MEETING_ID = uuid4()
TRANSCRIPT_ID = uuid4()
NOW = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
LEASE_UNTIL = NOW + timedelta(minutes=2)
LEASE_TOKEN = uuid4()


class _Transaction:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        self.session.events.append("transaction_started")

    async def __aexit__(self, exc_type, _exc, _tb):
        if exc_type is not None:
            self.session.events.append("transaction_rolled_back")
        elif self.session.commit_error:
            self.session.events.append("transaction_commit_failed")
            raise self.session.commit_error
        else:
            self.session.events.append("transaction_committed")
        return False


class _Session:
    def __init__(self, events, *, commit_error=None):
        self.events = events
        self.commit_error = commit_error

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
        return False


class _Repository:
    def __init__(self, session, *, acknowledge=True, ack_error=None):
        self.session = session
        self.acknowledge = acknowledge
        self.ack_error = ack_error

    async def acknowledge_published(self, event_id, lease_token, *, published_at):
        self.session.events.append(("ack", event_id, lease_token, published_at))
        if self.ack_error:
            raise self.ack_error
        return self.acknowledge

    async def record_failure(
        self, event_id, lease_token, *, category, failed_at, max_attempts,
        retry_base_seconds, retry_max_seconds,
    ):
        self.session.events.append((
            "failure", event_id, lease_token, category.value, failed_at,
            max_attempts, retry_base_seconds, retry_max_seconds,
        ))
        return True

    async def record_ambiguous_outcome(
        self, event_id, lease_token, *, failed_at, max_ambiguity_claims
    ):
        self.session.events.append((
            "ambiguous_failure", event_id, lease_token, failed_at, max_ambiguity_claims,
        ))
        return True


class JobOutboxRelayTests(unittest.TestCase):
    def test_relay_rejects_retry_settings_above_approved_policy(self):
        for options in (
            {"max_attempts": 4},
            {"retry_base_seconds": 2.01},
            {"retry_max_seconds": 60.01},
            {"retry_base_seconds": 2, "retry_max_seconds": 1},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                JobOutboxRelayService(
                    session_factory=lambda: None,
                    publisher=SimpleNamespace(publish_outbox_event=AsyncMock()),
                    **options,
                )

    def _event(self):
        return SimpleNamespace(
            id=EVENT_ID,
            job_id=JOB_ID,
            owner_id=OWNER_ID,
            event_type="ai.processing.requested.v1",
            payload={
                "job_id": str(JOB_ID),
                "meeting_id": str(MEETING_ID),
                "transcript_id": str(TRANSCRIPT_ID),
                "requested_operations": ["summary"],
            },
            status="pending",
            lock_token=LEASE_TOKEN,
            locked_until=LEASE_UNTIL,
            attempt_count=1,
            ambiguity_recovery_count=0,
            last_error_category="publication_outcome_unknown",
        )

    def _service(self, *, publisher=None, acknowledge=True, ack_error=None, commit_error=None):
        events = []
        session = _Session(events, commit_error=commit_error)
        repository = _Repository(session, acknowledge=acknowledge, ack_error=ack_error)
        publisher = publisher or SimpleNamespace(publish_outbox_event=AsyncMock())
        service = JobOutboxRelayService(
            session_factory=_SessionFactory(session),
            publisher=publisher,
            repository_factory=lambda _session: repository,
            clock=lambda: NOW,
        )
        return service, repository, publisher, events

    @staticmethod
    def _drive(coroutine):
        try:
            return coroutine.send(None)
        except StopIteration as completed:
            return completed.value
        raise AssertionError("Mock-only relay unexpectedly suspended on external I/O.")

    def test_publish_precedes_transactional_acknowledgment(self):
        service, _repository, publisher, events = self._service()
        publisher.publish_outbox_event.side_effect = lambda **_kwargs: events.append("broker_published")

        result = self._drive(service.publish_claimed(self._event()))

        self.assertEqual(result, EVENT_ID)
        publisher.publish_outbox_event.assert_awaited_once()
        args = publisher.publish_outbox_event.await_args.kwargs
        self.assertEqual(args["event_id"], EVENT_ID)
        self.assertEqual(args["owner_id"], OWNER_ID)
        self.assertEqual(args["job_id"], JOB_ID)
        self.assertEqual(args["payload"]["transcript_id"], str(TRANSCRIPT_ID))
        self.assertLess(events.index("broker_published"), events.index("transaction_started"))
        self.assertLess(events.index("transaction_started"), events.index("transaction_committed"))
        ack = next(item for item in events if isinstance(item, tuple) and item[0] == "ack")
        self.assertEqual(ack[2], LEASE_TOKEN)
        self.assertLess(
            next(i for i, item in enumerate(events) if isinstance(item, tuple) and item[0] == "ack"),
            events.index("transaction_committed"),
        )

    def test_broker_failure_does_not_ack_or_mark_event_published(self):
        from shared.jobs.outbox_policy import OutboxFailureCategory, OutboxPublicationError

        event = self._event()
        publisher = SimpleNamespace(
            publish_outbox_event=AsyncMock(
                side_effect=OutboxPublicationError(OutboxFailureCategory.BROKER_UNAVAILABLE)
            )
        )
        service, repository, _publisher, _events = self._service(publisher=publisher)

        with self.assertRaises(OutboxPublicationError):
            self._drive(service.publish_claimed(event))

        self.assertFalse(any(isinstance(item, tuple) and item[0] == "ack" for item in repository.session.events))
        self.assertEqual(event.status, "pending")
        failure = next(item for item in repository.session.events if isinstance(item, tuple) and item[0] == "failure")
        self.assertEqual(failure[1:4], (EVENT_ID, LEASE_TOKEN, "broker_unavailable"))

    def test_unknown_adapter_error_is_sanitized_and_recorded_as_operator_action(self):
        from shared.jobs.outbox_policy import OutboxPublicationError

        publisher = SimpleNamespace(
            publish_outbox_event=AsyncMock(
                side_effect=RuntimeError("secret=hidden redis://user:password@broker")
            )
        )
        service, repository, _publisher, _events = self._service(publisher=publisher)

        with self.assertRaises(OutboxPublicationError) as raised:
            self._drive(service.publish_claimed(self._event()))

        self.assertNotIn("password", str(raised.exception))
        failure = next(item for item in repository.session.events if isinstance(item, tuple) and item[0] == "ambiguous_failure")
        self.assertEqual(failure[1:3], (EVENT_ID, LEASE_TOKEN))

    def test_marker_is_present_before_external_publication_and_unknown_uses_separate_allowance(self):
        from shared.jobs.outbox_policy import OutboxFailureCategory, OutboxPublicationError

        event = self._event()
        publisher = SimpleNamespace(
            publish_outbox_event=AsyncMock(
                side_effect=OutboxPublicationError(
                    OutboxFailureCategory.PUBLICATION_OUTCOME_UNKNOWN
                )
            )
        )
        service, repository, _publisher, _events = self._service(publisher=publisher)
        with self.assertRaises(OutboxPublicationError):
            self._drive(service.publish_claimed(event))
        self.assertEqual(event.last_error_category, "publication_outcome_unknown")
        failure = next(
            item for item in repository.session.events
            if isinstance(item, tuple) and item[0] == "ambiguous_failure"
        )
        self.assertEqual(failure[-1], 1)

    def test_http_status_codes_and_safe_categories_are_classified(self):
        from httpx import Response
        from shared.jobs.outbox_policy import OutboxFailureCategory
        from app.services.ai_outbox_publication_client import AIOutboxPublicationClient

        cases = (
            (401, None, OutboxFailureCategory.AUTHENTICATION_REJECTED),
            (422, None, OutboxFailureCategory.REQUEST_REJECTED),
            (503, {"error": {"code": "outbox_configuration_invalid", "message": "secret"}}, OutboxFailureCategory.CONFIGURATION_INVALID),
            (503, {"error": {"code": "outbox_publication_outcome_unknown", "message": "secret"}}, OutboxFailureCategory.PUBLICATION_OUTCOME_UNKNOWN),
            (503, {"error": {"code": "outbox_protocol_error", "message": "secret"}}, OutboxFailureCategory.PUBLICATION_OUTCOME_UNKNOWN),
            (429, None, OutboxFailureCategory.BROKER_UNAVAILABLE),
        )
        for status_code, body, expected in cases:
            with self.subTest(status=status_code, expected=expected):
                response = Response(status_code, json=body) if body is not None else Response(status_code)
                self.assertEqual(AIOutboxPublicationClient._failure_category(response), expected)

    def test_malformed_and_unknown_5xx_categories_are_conservatively_ambiguous(self):
        from httpx import Response
        from shared.jobs.outbox_policy import OutboxFailureCategory
        from app.services.ai_outbox_publication_client import AIOutboxPublicationClient

        responses = (
            Response(503, json={"error": {"code": "unknown_category", "message": "private"}}),
            Response(503, json=[]),
            Response(503, text="private response detail"),
        )
        for response in responses:
            with self.subTest(response=response):
                self.assertEqual(
                    AIOutboxPublicationClient._failure_category(response),
                    OutboxFailureCategory.PUBLICATION_OUTCOME_UNKNOWN,
                )

    def test_missing_local_service_key_is_permanent_configuration_failure(self):
        from shared.config.base import AppEnv
        from shared.jobs.outbox_policy import OutboxFailureCategory, OutboxPublicationError
        from app.config.settings import MeetingSettings
        from app.services.ai_outbox_publication_client import AIOutboxPublicationClient

        client = AIOutboxPublicationClient(
            MeetingSettings(_env_file=None, app_env=AppEnv.TESTING)
        )
        with self.assertRaises(OutboxPublicationError) as raised:
            self._drive(client.publish_outbox_event(
                event_id=EVENT_ID,
                owner_id=OWNER_ID,
                job_id=JOB_ID,
                event_type="ai.processing.requested.v1",
                payload={"job_id": str(JOB_ID)},
            ))
        self.assertEqual(raised.exception.category, OutboxFailureCategory.CONFIGURATION_INVALID)

    def test_invalid_stored_event_is_permanent_and_never_contacts_ai(self):
        from shared.config.base import AppEnv
        from shared.jobs.outbox_policy import OutboxFailureCategory, OutboxPublicationError
        from app.config.settings import MeetingSettings
        from app.services.ai_outbox_publication_client import AIOutboxPublicationClient

        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_pem = private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        client = AIOutboxPublicationClient(MeetingSettings(
            _env_file=None,
            app_env=AppEnv.TESTING,
            outbox_publication_auth_private_key=private_pem,
        ))
        with self.assertRaises(OutboxPublicationError) as raised:
            self._drive(client.publish_outbox_event(
                event_id=EVENT_ID,
                owner_id=OWNER_ID,
                job_id=JOB_ID,
                event_type="unknown.event",
                payload={"job_id": str(JOB_ID)},
            ))
        self.assertEqual(raised.exception.category, OutboxFailureCategory.EVENT_INVALID)

    def test_transport_error_and_invalid_success_receipt_are_ambiguous(self):
        from httpx import ConnectTimeout, Response
        from shared.config.base import AppEnv
        from shared.jobs.outbox_policy import OutboxFailureCategory, OutboxPublicationError
        from app.config.settings import MeetingSettings
        from app.services.ai_outbox_publication_client import AIOutboxPublicationClient

        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_pem = private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        settings = MeetingSettings(
            _env_file=None,
            app_env=AppEnv.TESTING,
            outbox_publication_auth_private_key=private_pem,
        )
        client = AIOutboxPublicationClient(settings)
        results = (
            ConnectTimeout("private endpoint"),
            Response(202, json={"event_id": str(EVENT_ID), "job_id": str(OWNER_ID)}),
        )
        for result in results:
            downstream = MagicMock()
            if isinstance(result, Exception):
                downstream.post = AsyncMock(side_effect=result)
            else:
                downstream.post = AsyncMock(return_value=result)
            context = MagicMock()
            context.__aenter__ = AsyncMock(return_value=downstream)
            context.__aexit__ = AsyncMock(return_value=False)
            with self.subTest(result_type=type(result).__name__), patch(
                "app.services.ai_outbox_publication_client.httpx.AsyncClient",
                return_value=context,
            ):
                with self.assertRaises(OutboxPublicationError) as raised:
                    self._drive(client.publish_outbox_event(
                        event_id=EVENT_ID,
                        owner_id=OWNER_ID,
                        job_id=JOB_ID,
                        event_type="ai.processing.requested.v1",
                        payload={
                            "job_id": str(JOB_ID), "meeting_id": str(MEETING_ID),
                            "transcript_id": str(TRANSCRIPT_ID), "requested_operations": ["summary"],
                        },
                    ))
                self.assertEqual(
                    raised.exception.category,
                    OutboxFailureCategory.PUBLICATION_OUTCOME_UNKNOWN,
                )

    def test_ai_boundary_failure_does_not_ack_the_claimed_event(self):
        from httpx import Response
        from shared.config.base import AppEnv
        from shared.jobs.outbox_policy import OutboxPublicationError
        from app.config.settings import MeetingSettings
        from app.services.ai_outbox_publication_client import AIOutboxPublicationClient

        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_pem = private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        settings = MeetingSettings(
            _env_file=None,
            app_env=AppEnv.TESTING,
            outbox_publication_auth_private_key=private_pem,
        )
        downstream = MagicMock()
        downstream.post = AsyncMock(return_value=Response(503, text="untrusted details"))
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=downstream)
        context.__aexit__ = AsyncMock(return_value=False)
        publisher = AIOutboxPublicationClient(settings)
        service, repository, _publisher, _events = self._service(publisher=publisher)

        with patch("app.services.ai_outbox_publication_client.httpx.AsyncClient", return_value=context):
            with self.assertRaises(OutboxPublicationError):
                self._drive(service.publish_claimed(self._event()))

        self.assertFalse(
            any(isinstance(item, tuple) and item[0] == "ack" for item in repository.session.events)
        )

    def test_stale_lease_token_cannot_be_acknowledged(self):
        service, _repository, publisher, events = self._service(acknowledge=False)

        with self.assertRaises(OutboxLeaseLostError):
            self._drive(service.publish_claimed(self._event()))

        self.assertTrue(publisher.publish_outbox_event.await_count == 1)
        self.assertIn("transaction_rolled_back", events)

    def test_database_ack_failure_after_broker_success_is_not_reported_as_acknowledged(self):
        service, _repository, publisher, _events = self._service(
            ack_error=RuntimeError("database write failed")
        )

        with self.assertRaisesRegex(RuntimeError, "database write failed"):
            self._drive(service.publish_claimed(self._event()))

        publisher.publish_outbox_event.assert_awaited_once()
        published = publisher.publish_outbox_event.await_args.kwargs
        self.assertEqual(published["event_id"], EVENT_ID)
        self.assertEqual(published["job_id"], JOB_ID)

    def test_commit_failure_after_broker_delivery_is_propagated_for_redelivery(self):
        service, _repository, publisher, events = self._service(
            commit_error=RuntimeError("database commit failed")
        )

        with self.assertRaisesRegex(RuntimeError, "database commit failed"):
            self._drive(service.publish_claimed(self._event()))

        publisher.publish_outbox_event.assert_awaited_once()
        self.assertIn("transaction_commit_failed", events)
        self.assertNotIn("transaction_committed", events)


if __name__ == "__main__":
    unittest.main()
