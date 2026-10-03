"""Phase 9.3 broker configuration and opt-in live Redis/Celery execution."""

from __future__ import annotations

import asyncio
import importlib
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from celery import Celery
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

BACKEND_ROOT = Path(__file__).resolve().parents[1]
AI_ROOT = BACKEND_ROOT / "ai-service"
WORKER_ROOT = BACKEND_ROOT / "worker-service"
REPO_ROOT = BACKEND_ROOT.parent
JOB_ID = UUID("50000000-0000-0000-0000-000000000005")
MEETING_ID = UUID("30000000-0000-0000-0000-000000000003")
TRANSCRIPT_ID = UUID("40000000-0000-0000-0000-000000000004")
USER_ID = UUID("10000000-0000-0000-0000-000000000001")


class Phase9_3BrokerConfigurationTests(unittest.TestCase):
    def setUp(self):
        for name in list(sys.modules):
            if name == "app" or name.startswith("app.") or name == "worker_queue" or name.startswith("worker_queue.") or name == "agents" or name.startswith("agents.") or name == "shared.database" or name.startswith("shared.database.") or name == "openai" or name.startswith("openai."):
                del sys.modules[name]
        for root in (str(AI_ROOT), str(WORKER_ROOT), str(BACKEND_ROOT)):
            while root in sys.path:
                sys.path.remove(root)
        sys.path[:0] = [str(WORKER_ROOT), str(BACKEND_ROOT)]
        self.settings_module = importlib.import_module("app.config.settings")
        self.celery_module = importlib.import_module("worker_queue.celery_app")

    def tearDown(self):
        for name in list(sys.modules):
            if name == "app" or name.startswith("app.") or name == "worker_queue" or name.startswith("worker_queue."):
                del sys.modules[name]
        for root in (str(AI_ROOT), str(WORKER_ROOT), str(BACKEND_ROOT)):
            while root in sys.path:
                sys.path.remove(root)

    def test_redis_dsn_and_broker_timeouts_are_environment_driven(self):
        settings = self.settings_module.WorkerSettings(
            _env_file=None,
            celery_broker_url="rediss://worker:opaque@cache.example:6380/8",
            celery_broker_connection_timeout=3.5,
            celery_broker_socket_connect_timeout=2.0,
            celery_broker_socket_timeout=9.0,
        )
        app = self.celery_module.create_celery_app(settings)

        self.assertEqual(settings.celery_broker_url.scheme, "rediss")
        self.assertEqual(settings.celery_broker_url.path, "/8")
        self.assertEqual(app.conf.broker_connection_timeout, 3.5)
        self.assertTrue(app.conf.broker_connection_retry_on_startup)
        self.assertEqual(
            app.conf.broker_transport_options,
            {
                "socket_connect_timeout": 2.0,
                "socket_timeout": 9.0,
                "retry_on_timeout": True,
            },
        )
        self.assertIsNone(app.conf.result_backend)
        self.assertEqual(app.conf.task_serializer, "json")
        self.assertEqual(app.conf.accept_content, ["json"])
        self.assertEqual(app.conf.worker_concurrency, 1)
        self.assertEqual(app.conf.worker_prefetch_multiplier, 1)
        self.assertFalse(app.conf.task_acks_late)
        self.assertFalse(app.conf.task_reject_on_worker_lost)

    def test_importing_celery_app_does_not_open_redis_or_load_ai_or_database(self):
        self.assertFalse(any(name == "agents" or name.startswith("agents.") for name in sys.modules))
        self.assertFalse(any(name == "openai" or name.startswith("openai.") for name in sys.modules))
        self.assertFalse(any(name == "shared.database" or name.startswith("shared.database.") for name in sys.modules))
        # Building another app is configuration-only; no broker ping is made.
        self.celery_module.create_celery_app(
            self.settings_module.WorkerSettings(
                _env_file=None, celery_broker_url="redis://127.0.0.1:1/9"
            )
        )
        self.assertNotIn("redis", {name.split(".")[0] for name in sys.modules if name.startswith("redis")})

    def test_broker_timeout_settings_reject_invalid_values(self):
        for value in (0, -1, 61):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.settings_module.WorkerSettings(
                    _env_file=None, celery_broker_connection_timeout=value
                )


class Phase9_3SubmissionFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_publish_failure_runs_off_loop_and_is_sanitized(self):
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        for root in (str(AI_ROOT), str(WORKER_ROOT), str(BACKEND_ROOT)):
            while root in sys.path:
                sys.path.remove(root)
        sys.path[:0] = [str(BACKEND_ROOT), str(AI_ROOT)]
        jobs = importlib.import_module("app.background_processing")
        submission_module = importlib.import_module("app.celery_submission")
        context_type = importlib.import_module("shared.security.execution_context").TrustedExecutionContext
        context = context_type._issue_from_authenticated_user_id(USER_ID)
        job = jobs.AIProcessingJob.from_authenticated_context(
            job_id=JOB_ID,
            meeting_id=MEETING_ID,
            transcript_id=TRANSCRIPT_ID,
            requested_operations=["summary"],
            execution_context=context,
        )

        class SlowFailingPublisher:
            def send_task(self, *_args, **_kwargs):
                time.sleep(0.15)
                raise ConnectionError("redis://worker:do-not-leak@host.invalid:6379/1")

        port = submission_module.CeleryJobSubmissionPort(
            SlowFailingPublisher(), signing_key=_ephemeral_private_key()
        )
        submission = asyncio.create_task(port.submit(job))
        heartbeats = 0
        while not submission.done():
            heartbeats += 1
            await asyncio.sleep(0.01)
        with self.assertRaises(submission_module.CelerySubmissionError) as raised:
            await submission
        self.assertGreaterEqual(heartbeats, 5)
        self.assertNotIn("do-not-leak", str(raised.exception))
        self.assertNotIn("host.invalid", str(raised.exception))


def _ephemeral_private_key() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


@unittest.skipUnless(
    os.environ.get("RUN_REDIS_CELERY_INTEGRATION") == "1",
    "Set RUN_REDIS_CELERY_INTEGRATION=1 and provide a reachable Redis server.",
)
class LiveRedisCeleryExecutionTests(unittest.TestCase):
    def test_real_worker_executes_signed_job_through_phase8_and_ai_pipeline(self):
        from redis import Redis

        worker_settings_module = _import_worker_settings_module()
        settings = worker_settings_module.WorkerSettings()
        broker_url = str(settings.celery_broker_url)
        redis_client = Redis.from_url(
            broker_url,
            socket_connect_timeout=settings.celery_broker_socket_connect_timeout,
            socket_timeout=settings.celery_broker_socket_timeout,
            decode_responses=True,
        )
        try:
            redis_client.ping()
        except Exception:
            self.fail("The configured Redis broker is unavailable; no task was submitted.")

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        public_pem = private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
        report_key = f"phase9.3:integration:{uuid4()}"
        job_id = uuid4()
        redis_client.delete(report_key)

        worker_env = os.environ.copy()
        worker_env.update(
            {
                "PYTHONPATH": os.pathsep.join(
                    [
                        str(BACKEND_ROOT / "tests"),
                        str(WORKER_ROOT),
                        str(BACKEND_ROOT),
                        str(AI_ROOT),
                        str(BACKEND_ROOT / "meeting-service"),
                    ]
                ),
                "CELERY_BROKER_URL": broker_url,
                "BACKGROUND_JOB_VERIFICATION_PUBLIC_KEY": public_pem,
                "MANNERAI_REDIS_TEST_JOB_ID": str(job_id),
                "MANNERAI_REDIS_TEST_REPORT_KEY": report_key,
            }
        )
        command = [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "redis_celery_worker_bootstrap:celery_app",
            "worker",
            "--pool=solo",
            "--concurrency=1",
            "--prefetch-multiplier=1",
            "--loglevel=WARNING",
            "--hostname=phase93-integration@%h",
        ]
        worker = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            env=worker_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            publisher = Celery("phase9.3-integration-publisher", broker=broker_url, backend=None)
            publisher.conf.update(
                broker_connection_timeout=settings.celery_broker_connection_timeout,
                broker_transport_options={
                    "socket_connect_timeout": settings.celery_broker_socket_connect_timeout,
                    "socket_timeout": settings.celery_broker_socket_timeout,
                    "retry_on_timeout": True,
                },
                task_publish_retry=False,
            )
            self._wait_until_worker_ready(publisher, worker)
            self._submit_signed_test_job(private_pem, publisher, job_id)
            report = self._wait_for_report(redis_client, report_key, worker)
            self.assertEqual(report["job_id"], str(job_id))
            self.assertEqual(report["meeting_id"], str(MEETING_ID))
            self.assertEqual(report["transcript_id"], str(TRANSCRIPT_ID))
            self.assertEqual(report["requested_operations"], ["summary", "tasks"])
            self.assertEqual(report["user_id"], str(USER_ID))
            self.assertEqual(report["status"], "completed")
        finally:
            worker.terminate()
            try:
                worker.wait(timeout=8)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=5)
            redis_client.delete(report_key)
            redis_client.close()

    def _wait_until_worker_ready(self, publisher: Celery, worker: subprocess.Popen) -> None:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if worker.poll() is not None:
                self.fail("The Celery worker exited before becoming ready.")
            try:
                response = publisher.control.inspect(timeout=0.5).ping()
                if response:
                    return
            except Exception:
                pass
            time.sleep(0.25)
        self.fail("The Celery worker did not become ready within 30 seconds.")

    def _submit_signed_test_job(self, private_key: str, publisher: Celery, job_id: UUID) -> None:
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        for root in (str(AI_ROOT), str(WORKER_ROOT), str(BACKEND_ROOT)):
            while root in sys.path:
                sys.path.remove(root)
        sys.path[:0] = [str(BACKEND_ROOT), str(AI_ROOT)]
        jobs = importlib.import_module("app.background_processing")
        submission_module = importlib.import_module("app.celery_submission")
        context_type = importlib.import_module("shared.security.execution_context").TrustedExecutionContext
        context = context_type._issue_from_authenticated_user_id(USER_ID)
        job = jobs.AIProcessingJob.from_authenticated_context(
            job_id=job_id,
            meeting_id=MEETING_ID,
            transcript_id=TRANSCRIPT_ID,
            requested_operations=["summary", "tasks"],
            execution_context=context,
        )
        port = submission_module.CeleryJobSubmissionPort(
            publisher, signing_key=private_key
        )
        asyncio.run(port.submit(job))

    def _wait_for_report(self, redis_client, report_key: str, worker: subprocess.Popen):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if worker.poll() is not None:
                self.fail("The Celery worker exited before the job completed.")
            report = redis_client.get(report_key)
            if report is not None:
                import json

                return json.loads(report)
            time.sleep(0.1)
        self.fail("The signed Celery job was not consumed by the worker.")


def _import_worker_settings_module():
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    for root in (str(AI_ROOT), str(WORKER_ROOT), str(BACKEND_ROOT)):
        while root in sys.path:
            sys.path.remove(root)
    sys.path[:0] = [str(WORKER_ROOT), str(BACKEND_ROOT)]
    return importlib.import_module("app.config.settings")


if __name__ == "__main__":
    unittest.main()
