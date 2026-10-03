"""Phase 9.1 Celery, envelope, and fail-closed task boundary tests."""

from __future__ import annotations

import importlib
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from jose import jwt

BACKEND_ROOT = Path(__file__).resolve().parents[1]
AI_ROOT = BACKEND_ROOT / "ai-service"
WORKER_ROOT = BACKEND_ROOT / "worker-service"
MEETING_ID = UUID("30000000-0000-0000-0000-000000000003")
TRANSCRIPT_ID = UUID("40000000-0000-0000-0000-000000000004")
USER_ID = UUID("10000000-0000-0000-0000-000000000001")


def _clear_service_modules() -> None:
    for name in list(sys.modules):
        if any(
            name == package or name.startswith(f"{package}.")
            for package in ("app", "agents", "llm", "jobs", "worker_queue")
        ):
            del sys.modules[name]
    for root in (str(AI_ROOT), str(WORKER_ROOT), str(BACKEND_ROOT)):
        while root in sys.path:
            sys.path.remove(root)


class Phase9CeleryBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _clear_service_modules()
        sys.path[:0] = [str(BACKEND_ROOT), str(AI_ROOT)]
        self.job_module = importlib.import_module("app.background_processing")
        self.contracts = importlib.import_module("app.contracts")
        self.context_type = importlib.import_module(
            "shared.security.execution_context"
        ).TrustedExecutionContext
        self.envelope_module = importlib.import_module(
            "shared.schemas.ai_job_envelope"
        )
        self.submission_module = importlib.import_module("app.celery_submission")
        self.security = importlib.import_module(
            "shared.security.background_job_authorization"
        )
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.private_pem = self.private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        self.public_pem = self.private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.other_public_pem = other_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

    def tearDown(self) -> None:
        _clear_service_modules()

    def _context(self, user_id=USER_ID):
        return self.context_type._issue_from_authenticated_user_id(user_id)

    def _job(self, **updates):
        values = {
            "job_id": UUID("50000000-0000-0000-0000-000000000005"),
            "meeting_id": MEETING_ID,
            "transcript_id": TRANSCRIPT_ID,
            "requested_operations": ["summary", "tasks"],
            "context": None,
            "execution_context": self._context(),
        }
        values.update(updates)
        context = values.pop("execution_context")
        return self.job_module.AIProcessingJob.from_authenticated_context(
            **values, execution_context=context
        )

    def _load_worker_modules(self):
        for name in list(sys.modules):
            if any(
                name == package or name.startswith(f"{package}.")
                for package in ("app", "jobs", "worker_queue")
            ):
                del sys.modules[name]
        for root in (str(AI_ROOT), str(WORKER_ROOT), str(BACKEND_ROOT)):
            while root in sys.path:
                sys.path.remove(root)
        sys.path[:0] = [str(WORKER_ROOT), str(BACKEND_ROOT)]
        return (
            importlib.import_module("app.config.settings"),
            importlib.import_module("worker_queue.celery_app"),
            importlib.import_module("jobs.ai_processing_task"),
        )

    def test_worker_settings_defaults_env_override_and_invalid_broker(self):
        settings_module, _, _ = self._load_worker_modules()
        defaults = settings_module.WorkerSettings(_env_file=None)
        self.assertEqual(str(defaults.celery_broker_url), "redis://localhost:6379/1")
        self.assertEqual(defaults.celery_timezone, "UTC")
        self.assertEqual(defaults.celery_accept_content, ("json",))
        self.assertTrue(defaults.celery_task_acks_late)
        self.assertEqual(defaults.celery_worker_prefetch_multiplier, 1)
        self.assertEqual(defaults.celery_worker_concurrency, 1)

        with patch.dict(
            os.environ,
            {
                "CELERY_BROKER_URL": "rediss://cache.internal:6380/7",
                "CELERY_TASK_SERIALIZER": "json",
            },
        ):
            override = settings_module.WorkerSettings(_env_file=None)
        self.assertEqual(str(override.celery_broker_url), "rediss://cache.internal:6380/7")
        with self.assertRaises(ValueError):
            settings_module.WorkerSettings(
                _env_file=None, celery_broker_url="amqp://broker.local"
            )
        with self.assertRaises(ValueError):
            settings_module.WorkerSettings(_env_file=None, celery_task_serializer="pickle")
        with self.assertRaises(ValueError):
            settings_module.WorkerSettings(_env_file=None, celery_worker_concurrency=0)

    def test_celery_app_configures_json_utc_no_result_backend_without_connecting(self):
        persistence_modules_before = {
            name
            for name in sys.modules
            if name == "shared.database" or name.startswith("shared.database.")
        }
        provider_modules_before = {
            name for name in sys.modules if name == "openai" or name.startswith("openai.")
        }
        settings_module, celery_module, _ = self._load_worker_modules()
        settings = settings_module.WorkerSettings(_env_file=None)
        app = celery_module.create_celery_app(settings)

        self.assertEqual(app.conf.task_serializer, "json")
        self.assertEqual(app.conf.result_serializer, "json")
        self.assertEqual(app.conf.accept_content, ["json"])
        self.assertEqual(app.conf.timezone, "UTC")
        self.assertTrue(app.conf.enable_utc)
        self.assertEqual(app.conf.worker_concurrency, 1)
        self.assertEqual(app.conf.worker_prefetch_multiplier, 1)
        self.assertTrue(app.conf.task_acks_late)
        self.assertTrue(app.conf.task_reject_on_worker_lost)
        self.assertTrue(app.conf.task_ignore_result)
        self.assertIsNone(app.conf.result_backend)
        self.assertIn("jobs.ai_processing_task", app.conf.include)
        persistence_modules_after = {
            name
            for name in sys.modules
            if name == "shared.database" or name.startswith("shared.database.")
        }
        provider_modules_after = {
            name for name in sys.modules if name == "openai" or name.startswith("openai.")
        }
        self.assertEqual(persistence_modules_after, persistence_modules_before)
        self.assertEqual(provider_modules_after, provider_modules_before)

    def test_envelope_json_roundtrip_strict_fields_and_safe_errors(self):
        envelope_type = self.envelope_module.AIProcessingJobEnvelope
        job = self._job()
        envelope = envelope_type(
            job_id=job.job_id,
            meeting_id=job.meeting_id,
            transcript_id=job.transcript_id,
            requested_operations=[item.value for item in job.requested_operations],
        )
        wire = envelope.model_dump_json()
        restored = envelope_type.model_validate_json(wire)
        self.assertEqual(restored, envelope)
        for field in ("user_id", "execution_context", "access_token", "refresh_token"):
            self.assertNotIn(field, wire)
        with self.assertRaises(ValueError):
            envelope_type.model_validate_json(wire[:-1] + ',"user_id":"attacker"}')
        with self.assertRaises(ValueError):
            envelope_type.model_validate_json(
                wire.replace(str(MEETING_ID), "not-a-uuid")
            )
        with self.assertRaises(ValueError):
            envelope_type.model_validate_json(wire.replace('"tasks"', '"delete_all"'))
        with self.assertRaises(ValueError):
            envelope_type.model_validate_json(
                '{"job_id":"%s"}' % job.job_id
            )

    async def test_celery_submission_sends_only_envelope_and_preserves_job_identifier(self):
        job = self._job()
        published = SimpleNamespace(id=str(job.job_id))
        sender = MagicMock()
        sender.send_task = MagicMock(return_value=published)
        submission = self.submission_module.CeleryJobSubmissionPort(sender, signing_key=self.private_pem)

        receipt = await submission.submit(job)

        self.assertEqual(receipt.job_id, job.job_id)
        sender.send_task.assert_called_once()
        name = sender.send_task.call_args.args[0]
        kwargs = sender.send_task.call_args.kwargs
        self.assertEqual(name, "mannerai.process_ai_job")
        self.assertEqual(kwargs["task_id"], str(job.job_id))
        payload = kwargs["args"][0]
        self.assertEqual(payload["envelope"]["meeting_id"], str(MEETING_ID))
        self.assertEqual(payload["envelope"]["transcript_id"], str(TRANSCRIPT_ID))
        self.assertIsInstance(payload["authorization"], str)
        claims = jwt.decode(
            payload["authorization"],
            self.public_pem,
            algorithms=["RS256"],
            issuer="ai-service",
            audience="mannerai-worker",
        )
        self.assertEqual(claims["sub"], str(USER_ID))
        self.assertEqual(claims["job_id"], str(job.job_id))
        self.assertEqual(claims["type"], "background_job_authorization")
        for field in (
            "user_id", "execution_context", "execution_context_id", "access_token",
            "refresh_token", "password", "password_hash", "authorization_header",
            "database_session", "orm_object",
        ):
            self.assertNotIn(field, payload)
        self.assertNotIn(self.private_pem, str(payload))
        self.assertNotIn("AIProcessingService", str(sender.mock_calls))

    async def test_celery_submission_rejects_untrusted_context_and_propagates_broker_error(self):
        job = self._job(context=None)
        sender = MagicMock()
        sender.send_task = MagicMock(return_value=SimpleNamespace(id=str(job.job_id)))
        submission = self.submission_module.CeleryJobSubmissionPort(sender, signing_key=self.private_pem)

        untrusted_job = job.model_copy(
            update={"execution_context": self.context_type(user_id=USER_ID)},
            deep=True,
        )
        with self.assertRaises(self.job_module.InvalidJobTransitionError):
            await submission.submit(untrusted_job)

        with self.assertRaises(self.submission_module.UnsupportedQueueJobError):
            await submission.submit(self._job(context={"project": "launch"}))
        sender.send_task.assert_not_called()

        sender.send_task.side_effect = ConnectionError("broker credentials secret")
        with self.assertRaises(self.submission_module.CelerySubmissionError) as raised:
            await submission.submit(job)
        self.assertNotIn("secret", str(raised.exception))

    def test_submission_settings_factory_requires_configured_private_key(self):
        sender = MagicMock()
        with self.assertRaises(self.submission_module.CelerySubmissionError):
            self.submission_module.CeleryJobSubmissionPort.from_settings(
                sender, SimpleNamespace(background_job_signing_private_key=None)
            )
        configured = self.submission_module.CeleryJobSubmissionPort.from_settings(
            sender,
            SimpleNamespace(
                background_job_signing_private_key=__import__("pydantic").SecretStr(
                    self.private_pem
                ),
                background_job_issuer="ai-service",
                background_job_audience="mannerai-worker",
                background_job_authorization_expire_seconds=120,
            ),
        )
        self.assertIsInstance(configured, self.submission_module.CeleryJobSubmissionPort)

    def test_task_rejects_malformed_and_unconfigured_messages_without_ai_execution(self):
        _, _, task_module = self._load_worker_modules()
        task_module.configure_job_execution(None)

        with self.assertRaises(task_module.InvalidQueueEnvelopeError) as raised:
            task_module.process_ai_job.run(
                {"job_id": "bad", "access_token": "sensitive-value"}
            )
        self.assertNotIn("sensitive-value", str(raised.exception))
        valid_payload = {
            "envelope": {
                "job_id": "50000000-0000-0000-0000-000000000005",
                "meeting_id": str(MEETING_ID),
                "transcript_id": str(TRANSCRIPT_ID),
                "requested_operations": ["summary"],
            },
            "authorization": "not-verified-because-runtime-is-unconfigured",
        }
        with self.assertRaises(task_module.TrustedExecutionContextUnavailable):
            task_module.process_ai_job.run(valid_payload)
        with self.assertRaises(task_module.InvalidQueueEnvelopeError):
            task_module.process_ai_job.run(
                {
                    **valid_payload["envelope"],
                    "user_id": str(USER_ID),
                    "access_token": "must-not-be-accepted",
                }
            )

    def test_task_rejects_untrusted_identity_and_passes_trusted_job_to_executor(self):
        _, _, task_module = self._load_worker_modules()
        payload = {
            "job_id": "50000000-0000-0000-0000-000000000005",
            "meeting_id": str(MEETING_ID),
            "transcript_id": str(TRANSCRIPT_ID),
            "requested_operations": ["summary", "tasks"],
        }
        envelope = self.envelope_module.AIProcessingJobEnvelope.model_validate_json(
            __import__("json").dumps(payload)
        )
        token = self.security.issue_job_authorization(
            envelope, USER_ID, private_key=self.private_pem
        )
        message = {"envelope": payload, "authorization": token}
        executor = SimpleNamespace(execute=AsyncMock())

        async def execute(job):
            return job.start().fail(self.job_module.JobFailureCode.EXECUTION_FAILED)

        executor.execute.side_effect = execute
        runtime = SimpleNamespace(
            executor=executor,
            verification_key=self.public_pem,
            authorization_issuer="ai-service",
            authorization_audience="mannerai-worker",
            authorization_max_age_seconds=120,
            create_job=lambda incoming, trusted: self.job_module.AIProcessingJob.from_authenticated_context(
                job_id=incoming.job_id,
                meeting_id=incoming.meeting_id,
                transcript_id=incoming.transcript_id,
                requested_operations=list(incoming.requested_operations),
                execution_context=trusted,
            ),
        )
        task_module.configure_job_execution(runtime)

        result = task_module.process_ai_job.run(message)

        self.assertEqual(result, {"job_id": payload["job_id"], "status": "failed"})
        executor.execute.assert_awaited_once()
        sent_job = executor.execute.await_args.args[0]
        self.assertTrue(sent_job.execution_context.was_issued_by_authenticated_boundary)
        self.assertEqual(sent_job.execution_principal_id, USER_ID)
        self.assertEqual(sent_job.job_id, envelope.job_id)

        runtime.verification_key = self.other_public_pem
        executor.execute.reset_mock()
        with self.assertRaises(task_module.TrustedExecutionContextUnavailable):
            task_module.process_ai_job.run(message)
        executor.execute.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
