"""Authenticated Meeting-to-AI outbox publication boundary tests."""

from __future__ import annotations

import asyncio
import importlib
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

BACKEND = Path(__file__).resolve().parents[1]
AI_ROOT = BACKEND / "ai-service"
MEETING_ROOT = BACKEND / "meeting-service"
OWNER_ID = UUID("10000000-0000-0000-0000-000000000001")
MEETING_ID = UUID("30000000-0000-0000-0000-000000000003")
TRANSCRIPT_ID = UUID("40000000-0000-0000-0000-000000000004")
JOB_ID = UUID("50000000-0000-0000-0000-000000000005")
EVENT_ID = UUID("60000000-0000-0000-0000-000000000006")


def _keys() -> tuple[str, str]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


def _drive_immediate(coroutine):
    try:
        return coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("Mocked HTTP boundary unexpectedly suspended.")


async def _immediate_to_thread(function, *args, **kwargs):
    return function(*args, **kwargs)


def _load_service(service_root: Path):
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    for root in (str(AI_ROOT), str(MEETING_ROOT), str(BACKEND)):
        while root in sys.path:
            sys.path.remove(root)
    sys.path[:0] = [str(service_root), str(BACKEND)]


class OutboxPublicationBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        _load_service(AI_ROOT)
        from app.config.settings import AISettings
        from shared.config.base import AppEnv

        self.meeting_private, self.meeting_public = _keys()
        self.ai_private, self.ai_public = _keys()
        self.settings = AISettings(
            _env_file=None,
            app_env=AppEnv.TESTING,
            outbox_publication_auth_public_key=self.meeting_public,
            background_job_signing_private_key=self.ai_private,
            celery_broker_url="redis://localhost:6379/1",
        )
        self.routes = importlib.import_module("app.routes")
        self.auth = importlib.import_module("app.auth")
        self.sender = MagicMock()
        self.sender.send_task.return_value = SimpleNamespace(id=str(JOB_ID))
        self.port = importlib.import_module("app.celery_submission").CeleryJobSubmissionPort.from_settings(
            self.sender, self.settings
        )

    def tearDown(self) -> None:
        self.sender.reset_mock()

    def _service_token(self, *, private_key: str | None = None, audience: str | None = None) -> str:
        from shared.security.service_principal import create_service_principal

        return create_service_principal(
            "meeting-service",
            private_key=private_key or self.meeting_private,
            issuer="meeting-service",
            audience=audience or "ai-service:outbox-publication",
            expires_seconds=60,
        )

    def _payload(self, *, body_job_id: UUID = JOB_ID) -> dict[str, object]:
        return {
            "event_id": str(EVENT_ID),
            "owner_id": str(OWNER_ID),
            "job_id": str(JOB_ID),
            "event_type": "ai.processing.requested.v1",
            "payload": {
                "job_id": str(body_job_id),
                "meeting_id": str(MEETING_ID),
                "transcript_id": str(TRANSCRIPT_ID),
                "requested_operations": ["summary", "tasks"],
            },
        }

    def _request(self, *, body_job_id: UUID = JOB_ID):
        from shared.schemas.outbox_publication import OutboxPublicationRequest

        import json

        return OutboxPublicationRequest.model_validate_json(
            json.dumps(self._payload(body_job_id=body_job_id))
        )

    def _publish(self, payload=None):
        body = payload or self._request()
        with patch.object(asyncio, "to_thread", new=_immediate_to_thread):
            return _drive_immediate(
                self.routes.publish_outbox_event(
                    body,
                    _service_id="meeting-service",
                    publisher=self.port,
                )
            )

    def test_missing_and_invalid_service_auth_reject_without_publishing(self) -> None:
        from fastapi.security import HTTPAuthorizationCredentials
        from shared.exceptions.common import UnauthorizedError

        with self.assertRaises(UnauthorizedError):
            _drive_immediate(self.auth.get_authenticated_outbox_publisher(None, self.settings))
        with self.assertRaises(UnauthorizedError):
            _drive_immediate(
                self.auth.get_authenticated_outbox_publisher(
                    HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid"),
                    self.settings,
                )
            )
        self.sender.send_task.assert_not_called()

    def test_expired_wrong_issuer_and_wrong_subject_service_tokens_are_rejected(self) -> None:
        from fastapi.security import HTTPAuthorizationCredentials
        from shared.exceptions.common import UnauthorizedError

        now = datetime.now(timezone.utc)
        invalid_claim_sets = (
            {
                "sub": "meeting-service",
                "type": "service_principal",
                "iss": "meeting-service",
                "aud": "ai-service:outbox-publication",
                "iat": now - timedelta(minutes=2),
                "exp": now - timedelta(minutes=1),
            },
            {
                "sub": "meeting-service",
                "type": "service_principal",
                "iss": "another-service",
                "aud": "ai-service:outbox-publication",
                "iat": now,
                "exp": now + timedelta(minutes=1),
            },
            {
                "sub": "another-service",
                "type": "service_principal",
                "iss": "meeting-service",
                "aud": "ai-service:outbox-publication",
                "iat": now,
                "exp": now + timedelta(minutes=1),
            },
        )

        for claims in invalid_claim_sets:
            with self.subTest(claim=claims["sub"], issuer=claims["iss"]):
                token = jwt.encode(claims, self.meeting_private, algorithm="RS256")
                with self.assertRaises(UnauthorizedError):
                    _drive_immediate(
                        self.auth.get_authenticated_outbox_publisher(
                            HTTPAuthorizationCredentials(scheme="Bearer", credentials=token),
                            self.settings,
                        )
                    )

        self.sender.send_task.assert_not_called()

    def test_ai_service_rejects_reused_gateway_or_job_signing_public_keys(self) -> None:
        from pydantic import ValidationError

        for reused_public_key in (self.settings.internal_principal_public_key, self.ai_public):
            with self.subTest(key_kind="gateway_or_job_signing"), self.assertRaises(ValidationError):
                type(self.settings)(
                    _env_file=None,
                    app_env=self.settings.app_env,
                    outbox_publication_auth_public_key=reused_public_key,
                    background_job_signing_private_key=self.ai_private,
                    celery_broker_url="redis://localhost:6379/1",
                )

    def test_internal_publication_route_is_mounted_and_worker_has_no_private_signing_setting(self) -> None:
        from app.config.settings import AISettings
        from app.main import app

        routes = {
            (method, route.path)
            for route in app.routes
            for method in getattr(route, "methods", set())
        }
        self.assertIn(("POST", "/internal/jobs/outbox-events"), routes)
        publication_route = next(
            route
            for route in app.routes
            if getattr(route, "path", None) == "/internal/jobs/outbox-events"
        )
        dependency_calls = {dependency.call for dependency in publication_route.dependant.dependencies}
        self.assertIn(self.auth.get_authenticated_outbox_publisher, dependency_calls)
        self.assertIn(self.routes.get_outbox_publication_port, dependency_calls)
        self.assertIn("outbox_publication_auth_public_key", AISettings.model_fields)
        self.assertIn("background_job_signing_private_key", AISettings.model_fields)
        sender_generator = self.routes.get_celery_task_sender(self.settings)
        sender = next(sender_generator)
        self.assertEqual(str(sender.conf.broker_url), str(self.settings.celery_broker_url))
        self.assertEqual(sender.conf.task_serializer, "json")
        self.assertEqual(sender.conf.accept_content, ["json"])
        with self.assertRaises(StopIteration):
            next(sender_generator)

        _load_service(MEETING_ROOT)
        meeting_settings = importlib.import_module("app.config.settings").MeetingSettings
        self.assertIn("outbox_publication_auth_private_key", meeting_settings.model_fields)
        self.assertNotIn("background_job_signing_private_key", meeting_settings.model_fields)

        _load_service(BACKEND / "worker-service")
        worker_settings = importlib.import_module("app.config.settings").WorkerSettings
        self.assertNotIn("background_job_signing_private_key", worker_settings.model_fields)
        self.assertNotIn("outbox_publication_auth_private_key", worker_settings.model_fields)

    def test_valid_service_auth_signs_and_publishes_existing_task_contract(self) -> None:
        from fastapi.security import HTTPAuthorizationCredentials

        authenticated = _drive_immediate(
            self.auth.get_authenticated_outbox_publisher(
                HTTPAuthorizationCredentials(
                    scheme="Bearer", credentials=self._service_token()
                ),
                self.settings,
            )
        )
        self.assertEqual(authenticated, "meeting-service")
        response = self._publish()

        self.assertEqual(response.model_dump(mode="json"), {"event_id": str(EVENT_ID), "job_id": str(JOB_ID)})
        self.sender.send_task.assert_called_once()
        args, kwargs = self.sender.send_task.call_args
        self.assertEqual(args[0], "mannerai.process_ai_job")
        self.assertEqual(kwargs["task_id"], str(JOB_ID))
        self.assertEqual(kwargs["headers"]["outbox_event_id"], str(EVENT_ID))
        message = kwargs["args"][0]
        claims = jwt.decode(
            message["authorization"],
            self.ai_public,
            algorithms=["RS256"],
            issuer="ai-service",
            audience="mannerai-worker",
        )
        self.assertEqual(claims["sub"], str(OWNER_ID))
        self.assertNotIn(self.ai_private, str(message))

    def test_published_outbox_job_is_consumed_by_registered_worker_task(self) -> None:
        from app.background_processing import AIProcessingJob, JobFailureCode
        from shared.security.execution_context import TrustedExecutionContext

        response = self._publish()
        self.assertEqual(response.event_id, EVENT_ID)
        self.assertEqual(response.job_id, JOB_ID)
        self.sender.send_task.assert_called_once()
        task_args, task_kwargs = self.sender.send_task.call_args
        self.assertEqual(task_args[0], "mannerai.process_ai_job")
        self.assertEqual(task_kwargs["task_id"], str(JOB_ID))
        self.assertEqual(task_kwargs["headers"]["outbox_event_id"], str(EVENT_ID))

        worker_root = BACKEND / "worker-service"
        _load_service(worker_root)
        task_module = importlib.import_module("jobs.ai_processing_task")
        celery_module = importlib.import_module("worker_queue.celery_app")
        self.assertEqual(task_module.process_ai_job.name, "mannerai.process_ai_job")
        self.assertIn("jobs.ai_processing_task", celery_module.celery_app.conf.include)

        observed_jobs = []

        class Executor:
            async def execute(self, job):
                observed_jobs.append(job)
                return job.start().fail(JobFailureCode.EXECUTION_FAILED)

        def create_job(envelope, execution_context):
            return AIProcessingJob.from_authenticated_context(
                job_id=envelope.job_id,
                meeting_id=envelope.meeting_id,
                transcript_id=envelope.transcript_id,
                requested_operations=list(envelope.requested_operations),
                execution_context=execution_context,
            )

        task_module.configure_job_execution(SimpleNamespace(
            executor=Executor(),
            verification_key=self.ai_public,
            authorization_issuer="ai-service",
            authorization_audience="mannerai-worker",
            authorization_max_age_seconds=120,
            create_job=create_job,
        ))
        with patch.object(task_module.asyncio, "run", new=_drive_immediate):
            result = task_module.process_ai_job.run(task_kwargs["args"][0])

        self.assertEqual(result, {"job_id": str(JOB_ID), "status": "failed"})
        self.assertEqual(len(observed_jobs), 1)
        executed_job = observed_jobs[0]
        self.assertEqual(executed_job.job_id, JOB_ID)
        self.assertEqual(executed_job.meeting_id, MEETING_ID)
        self.assertEqual(executed_job.transcript_id, TRANSCRIPT_ID)
        self.assertEqual(executed_job.execution_principal_id, OWNER_ID)
        self.assertIsInstance(executed_job.execution_context, TrustedExecutionContext)
        self.assertTrue(executed_job.execution_context.was_issued_by_authenticated_boundary)

    def test_wrong_audience_and_mismatched_event_job_contract_are_rejected(self) -> None:
        from fastapi.security import HTTPAuthorizationCredentials
        from pydantic import ValidationError
        from shared.exceptions.common import UnauthorizedError

        with self.assertRaises(UnauthorizedError):
            _drive_immediate(
                self.auth.get_authenticated_outbox_publisher(
                    HTTPAuthorizationCredentials(
                        scheme="Bearer", credentials=self._service_token(audience="ai-service")
                    ),
                    self.settings,
                )
            )
        with self.assertRaises(ValidationError):
            self._request(body_job_id=MEETING_ID)

        self.sender.send_task.assert_not_called()

    def test_broker_failure_is_sanitized_as_unavailable(self) -> None:
        from shared.exceptions.common import ServiceUnavailableError

        self.sender.send_task.side_effect = ConnectionError("redis://user:secret@broker/1")
        with self.assertRaises(ServiceUnavailableError) as raised:
            self._publish()
        self.assertNotIn("secret", str(raised.exception))
        self.assertEqual(raised.exception.code, "outbox_publication_outcome_unknown")

    def test_missing_ai_signing_configuration_has_permanent_machine_category(self) -> None:
        from app.config.settings import AISettings
        from shared.exceptions.common import ServiceUnavailableError

        unconfigured = AISettings(
            _env_file=None,
            app_env=self.settings.app_env,
            outbox_publication_auth_public_key=self.meeting_public,
            celery_broker_url="redis://localhost:6379/1",
        )
        with self.assertRaises(ServiceUnavailableError) as raised:
            self.routes.get_outbox_publication_port(self.sender, unconfigured)
        self.assertEqual(raised.exception.code, "outbox_configuration_invalid")
        self.assertNotIn("broker", str(raised.exception))

    def test_duplicate_requests_keep_event_and_job_identity(self) -> None:
        for _ in range(2):
            receipt = self._publish()
            self.assertEqual(receipt.event_id, EVENT_ID)
            self.assertEqual(receipt.job_id, JOB_ID)
        self.assertEqual(self.sender.send_task.call_count, 2)
        for _args, kwargs in self.sender.send_task.call_args_list:
            self.assertEqual(kwargs["task_id"], str(JOB_ID))
            self.assertEqual(kwargs["headers"]["outbox_event_id"], str(EVENT_ID))


class MeetingOutboxPublicationClientTests(unittest.TestCase):
    def setUp(self) -> None:
        _load_service(MEETING_ROOT)
        from app.config.settings import MeetingSettings
        from shared.config.base import AppEnv

        self.meeting_private, self.meeting_public = _keys()
        self.ai_private, self.ai_public = _keys()
        self.settings = MeetingSettings(
            _env_file=None,
            app_env=AppEnv.TESTING,
            outbox_publication_auth_private_key=self.meeting_private,
            ai_service_url="http://ai-service:8002",
        )

    def test_client_sends_service_identity_contract_and_request_id(self) -> None:
        from httpx import Response
        from shared.security.service_principal import verify_service_principal
        from app.services.ai_outbox_publication_client import AIOutboxPublicationClient

        downstream = MagicMock()
        downstream.post = AsyncMock(return_value=Response(202, json={
            "event_id": str(EVENT_ID), "job_id": str(JOB_ID),
        }))
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=downstream)
        context.__aexit__ = AsyncMock(return_value=False)
        client = AIOutboxPublicationClient(self.settings, request_id="outbox-request-1")
        with patch("app.services.ai_outbox_publication_client.httpx.AsyncClient", return_value=context):
            _drive_immediate(client.publish_outbox_event(
                event_id=EVENT_ID,
                owner_id=OWNER_ID,
                job_id=JOB_ID,
                event_type="ai.processing.requested.v1",
                payload={
                    "job_id": str(JOB_ID), "meeting_id": str(MEETING_ID),
                    "transcript_id": str(TRANSCRIPT_ID), "requested_operations": ["summary"],
                },
            ))

        kwargs = downstream.post.await_args.kwargs
        self.assertEqual(kwargs["headers"]["X-Request-ID"], "outbox-request-1")
        token = kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        self.assertEqual(
            verify_service_principal(
                token,
                public_key=self.meeting_public,
                issuer="meeting-service",
                audience="ai-service:outbox-publication",
                subject="meeting-service",
            ),
            "meeting-service",
        )

    def test_downstream_failure_is_sanitized_and_never_claims_success(self) -> None:
        from httpx import Response
        from shared.jobs.outbox_policy import OutboxFailureCategory, OutboxPublicationError
        from app.services.ai_outbox_publication_client import AIOutboxPublicationClient

        downstream = MagicMock()
        downstream.post = AsyncMock(return_value=Response(503, text="private broker credential"))
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=downstream)
        context.__aexit__ = AsyncMock(return_value=False)
        client = AIOutboxPublicationClient(self.settings)
        with patch("app.services.ai_outbox_publication_client.httpx.AsyncClient", return_value=context):
            with self.assertRaises(OutboxPublicationError) as raised:
                _drive_immediate(client.publish_outbox_event(
                    event_id=EVENT_ID,
                    owner_id=OWNER_ID,
                    job_id=JOB_ID,
                    event_type="ai.processing.requested.v1",
                    payload={
                        "job_id": str(JOB_ID), "meeting_id": str(MEETING_ID),
                        "transcript_id": str(TRANSCRIPT_ID), "requested_operations": ["summary"],
                    },
                ))
        self.assertNotIn("credential", str(raised.exception))
        self.assertEqual(raised.exception.category, OutboxFailureCategory.PUBLICATION_OUTCOME_UNKNOWN)


if __name__ == "__main__":
    unittest.main()
