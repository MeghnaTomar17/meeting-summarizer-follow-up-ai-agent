"""Unit tests for Phase 9.4 durable job lifecycle policy."""

from __future__ import annotations

import asyncio
import importlib
import sys
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

BACKEND_ROOT = Path(__file__).resolve().parents[1]
WORKER_ROOT = BACKEND_ROOT / "worker-service"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKER_ROOT))

from shared.database.models.processing_job import ProcessingJobRecord
from shared.jobs.lifecycle import (
    FailureCategory,
    JobStatus,
    LifecycleIdentityError,
    ProcessingJobService,
)

JOB_ID = UUID("50000000-0000-0000-0000-000000000005")
MEETING_ID = UUID("30000000-0000-0000-0000-000000000003")
TRANSCRIPT_ID = UUID("40000000-0000-0000-0000-000000000004")
OWNER_ID = UUID("10000000-0000-0000-0000-000000000001")


class _Transaction:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        await self._session.lock.acquire()

    async def __aexit__(self, *_):
        self._session.lock.release()


class _Session:
    def __init__(self, records):
        self.records = records
        self.lock = asyncio.Lock()

    def begin(self):
        return _Transaction(self)


class _Repository:
    def __init__(self, session):
        self.session = session

    async def create_if_absent(self, record):
        self.session.records.setdefault(record.job_id, record)
        return self.session.records[record.job_id]

    async def get_by_id(self, job_id, *, for_update=False):
        return self.session.records.get(job_id)

    async def update(self, record):
        self.session.records[record.job_id] = record
        return record


def service_for(session, *, max_attempts=3, base=2, maximum=5):
    return ProcessingJobService(
        session,
        _Repository(session),
        max_attempts=max_attempts,
        retry_base_seconds=base,
        retry_max_seconds=maximum,
        lease_seconds=60,
    )


class Phase9_4JobLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.records = {}
        self.session = _Session(self.records)
        self.service = service_for(self.session)
        self.now = datetime(2026, 10, 3, tzinfo=timezone.utc)
        await self.service.register(
            job_id=JOB_ID,
            meeting_id=MEETING_ID,
            transcript_id=TRANSCRIPT_ID,
            owner_id=OWNER_ID,
            requested_operations=["summary", "tasks"],
        )

    async def claim(self, service=None, *, now=None):
        return await (service or self.service).claim(
            job_id=JOB_ID,
            meeting_id=MEETING_ID,
            transcript_id=TRANSCRIPT_ID,
            owner_id=OWNER_ID,
            requested_operations=["summary", "tasks"],
            now=now or self.now,
        )

    async def test_registration_is_idempotent_and_rejects_job_id_rebinding(self):
        again = await self.service.register(
            job_id=JOB_ID,
            meeting_id=MEETING_ID,
            transcript_id=TRANSCRIPT_ID,
            owner_id=OWNER_ID,
            requested_operations=["summary", "tasks"],
        )
        self.assertEqual(again.job_id, JOB_ID)
        self.assertEqual(len(self.records), 1)
        with self.assertRaises(LifecycleIdentityError):
            await self.service.register(
                job_id=JOB_ID,
                meeting_id=MEETING_ID,
                transcript_id=TRANSCRIPT_ID,
                owner_id=uuid4(),
                requested_operations=["summary", "tasks"],
            )

    async def test_claim_is_atomic_and_duplicate_delivery_does_not_increment(self):
        second = service_for(self.session)
        first, concurrent = await asyncio.gather(
            self.claim(), self.claim(second)
        )
        self.assertEqual(sum(item.outcome == "claimed" for item in (first, concurrent)), 1)
        self.assertEqual(sum(item.outcome == "already_running" for item in (first, concurrent)), 1)
        self.assertEqual(self.records[JOB_ID].attempt_count, 1)

    async def test_retryable_transient_failure_uses_bounded_exponential_backoff(self):
        claim = await self.claim()
        first = await self.service.fail(
            JOB_ID,
            claim.lease_token,
            category=FailureCategory.TRANSIENT_INFRASTRUCTURE,
            retryable=True,
            now=self.now,
        )
        self.assertEqual((first.status, first.retry, first.retry_after_seconds), (JobStatus.QUEUED, True, 2))
        self.assertEqual(self.records[JOB_ID].failure_category, FailureCategory.TRANSIENT_INFRASTRUCTURE.value)
        early = await self.claim(now=self.now.replace(second=1))
        self.assertEqual(early.outcome, "not_due")
        second_claim = await self.claim(now=self.now.replace(second=2))
        second_failure = await self.service.fail(
            JOB_ID,
            second_claim.lease_token,
            category=FailureCategory.TRANSIENT_INFRASTRUCTURE,
            retryable=True,
            now=self.now.replace(second=2),
        )
        self.assertEqual(second_failure.retry_after_seconds, 4)
        third_claim = await self.claim(now=self.now.replace(second=6))
        exhausted = await self.service.fail(
            JOB_ID,
            third_claim.lease_token,
            category=FailureCategory.TRANSIENT_INFRASTRUCTURE,
            retryable=True,
            now=self.now.replace(second=6),
        )
        self.assertEqual(exhausted.status, JobStatus.FAILED)
        self.assertFalse(exhausted.retry)
        self.assertEqual(self.records[JOB_ID].failure_category, FailureCategory.ATTEMPTS_EXHAUSTED.value)
        self.assertEqual(self.records[JOB_ID].attempt_count, 3)

    async def test_permanent_or_security_failure_is_never_retried(self):
        for category in (FailureCategory.PERMANENT_VALIDATION, FailureCategory.SECURITY):
            with self.subTest(category=category):
                local_records = {}
                session = _Session(local_records)
                service = service_for(session)
                await service.register(job_id=JOB_ID, meeting_id=MEETING_ID, transcript_id=TRANSCRIPT_ID, owner_id=OWNER_ID, requested_operations=["summary"])
                claim = await service.claim(job_id=JOB_ID, meeting_id=MEETING_ID, transcript_id=TRANSCRIPT_ID, owner_id=OWNER_ID, requested_operations=["summary"], now=self.now)
                failed = await service.fail(JOB_ID, claim.lease_token, category=category, retryable=True, now=self.now)
                self.assertEqual(failed.status, JobStatus.FAILED)
                self.assertFalse(failed.retry)

    async def test_terminal_states_cannot_be_claimed_again(self):
        claim = await self.claim()
        partial_payload = {"results": [{"operation": "summary", "status": "completed", "output": {"content": "safe mapped result"}}, {"operation": "tasks", "status": "failed", "error": {"code": "provider_timeout", "message": "The model provider timed out."}}]}
        self.assertTrue(await self.service.complete(JOB_ID, claim.lease_token, status=JobStatus.PARTIAL, result=partial_payload))
        terminal = await self.claim()
        self.assertEqual(terminal.outcome, "terminal")
        self.assertEqual(terminal.status, JobStatus.PARTIAL)
        self.assertEqual(self.records[JOB_ID].attempt_count, 1)
        self.assertEqual(self.records[JOB_ID].result, partial_payload)

    async def test_expired_lease_can_be_reclaimed_but_stale_worker_cannot_complete(self):
        first = await self.claim()
        second = await self.claim(now=self.now.replace(minute=16))
        self.assertEqual(second.outcome, "claimed")
        self.assertEqual(second.attempt, 2)
        self.assertFalse(await self.service.complete(JOB_ID, first.lease_token, status=JobStatus.COMPLETED, result={}))
        self.assertTrue(await self.service.complete(JOB_ID, second.lease_token, status=JobStatus.COMPLETED, result={"results": []}))


class Phase9_4SchemaTests(unittest.TestCase):
    def test_model_and_forward_migration_describe_durable_job_constraints(self):
        self.assertEqual(ProcessingJobRecord.__table__.primary_key.columns.keys(), ["job_id"])
        self.assertIn("ix_processing_jobs_status_created_at", {item.name for item in ProcessingJobRecord.__table__.indexes})
        migration = (BACKEND_ROOT / "migrations" / "versions" / "0006_processing_jobs.py").read_text(encoding="utf-8")
        self.assertIn('down_revision: Union[str, None] = "0005_meeting_insights"', migration)
        self.assertIn("lease_token", migration)


class Phase9_4WorkerBoundaryTests(unittest.TestCase):
    def test_invalid_authorization_is_rejected_before_lifecycle_lookup(self):
        from types import SimpleNamespace

        for module_name in list(sys.modules):
            if module_name == "app" or module_name.startswith("app.") or module_name == "jobs" or module_name.startswith("jobs."):
                del sys.modules[module_name]
        while str(WORKER_ROOT) in sys.path:
            sys.path.remove(str(WORKER_ROOT))
        sys.path.insert(0, str(WORKER_ROOT))
        task = __import__("jobs.ai_processing_task", fromlist=["execute_job_envelope"])

        class LifecycleSpy:
            calls = 0

            async def claim(self, **_):
                self.calls += 1

        lifecycle = LifecycleSpy()
        task.configure_job_execution(SimpleNamespace(
            executor=SimpleNamespace(execute=None),
            lifecycle=lifecycle,
            verification_key="not a key",
            authorization_issuer="ai-service",
            authorization_audience="mannerai-worker",
            authorization_max_age_seconds=120,
            create_job=lambda *_: self.fail("job creation must not happen"),
        ))
        payload = {
            "envelope": {
                "job_id": str(JOB_ID),
                "meeting_id": str(MEETING_ID),
                "transcript_id": str(TRANSCRIPT_ID),
                "requested_operations": ["summary"],
            },
            "authorization": "invalid.signed.message",
        }
        try:
            with self.assertRaises(task.TrustedExecutionContextUnavailable):
                task.execute_job_envelope(payload)
            self.assertEqual(lifecycle.calls, 0)
        finally:
            task.configure_job_execution(None)

    def test_provider_transient_failure_is_retryable_only_for_full_failure(self):
        from types import SimpleNamespace

        while str(WORKER_ROOT) in sys.path:
            sys.path.remove(str(WORKER_ROOT))
        sys.path.insert(0, str(WORKER_ROOT))
        task = __import__("jobs.ai_processing_task", fromlist=["_is_transient_processing_failure"])
        full_failure = SimpleNamespace(
            status=SimpleNamespace(value="failed"),
            processing_result=SimpleNamespace(
                status=SimpleNamespace(value="failed"),
                results=[SimpleNamespace(error=SimpleNamespace(code=SimpleNamespace(value="provider_timeout")))],
            ),
        )
        partial_failure = SimpleNamespace(
            status=SimpleNamespace(value="partially_failed"),
            processing_result=SimpleNamespace(
                status=SimpleNamespace(value="partially_failed"),
                results=[SimpleNamespace(error=SimpleNamespace(code=SimpleNamespace(value="provider_timeout")))],
            ),
        )
        self.assertTrue(task._is_transient_processing_failure(full_failure))
        self.assertFalse(task._is_transient_processing_failure(partial_failure))
        execution_failure = SimpleNamespace(
            failure=SimpleNamespace(code=SimpleNamespace(value="execution_failed")),
            processing_result=None,
        )
        self.assertTrue(task._is_transient_processing_failure(execution_failure))

    def test_meeting_target_rejection_marks_failed_before_claim_or_ai(self):
        from types import SimpleNamespace

        while str(WORKER_ROOT) in sys.path:
            sys.path.remove(str(WORKER_ROOT))
        sys.path.insert(0, str(WORKER_ROOT))
        task = __import__("jobs.ai_processing_task", fromlist=["_execute_with_lifecycle"])
        from shared.jobs.lifecycle import ClaimResult, JobStatus, JobTargetRejectedError

        class LifecycleSpy:
            claimed = False
            rejected = False

            async def validate_registered(self, **_):
                return ClaimResult("registered", JobStatus.QUEUED, 0)

            async def reject_before_claim(self, **kwargs):
                self.rejected = kwargs["expected_status"] == JobStatus.QUEUED
                return self.rejected

            async def claim(self, **_):
                self.claimed = True
                raise AssertionError("invalid target must not be claimed")

        class Executor:
            async def execute(self, _):
                raise AssertionError("invalid target must not reach AI execution")

        lifecycle = LifecycleSpy()

        async def reject_target(_job):
            raise JobTargetRejectedError()

        runtime = SimpleNamespace(lifecycle=lifecycle, executor=Executor(), authorize_target=reject_target)
        envelope = SimpleNamespace(
            job_id=JOB_ID,
            meeting_id=MEETING_ID,
            transcript_id=TRANSCRIPT_ID,
            requested_operations=[SimpleNamespace(value="summary")],
        )
        job = SimpleNamespace()
        result = asyncio.run(task._execute_with_lifecycle(runtime, envelope, job, OWNER_ID))
        self.assertEqual(result["outcome"], "target_rejected")
        self.assertTrue(lifecycle.rejected)
        self.assertFalse(lifecycle.claimed)


class Phase9_4SubmissionCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_persistent_record_is_registered_before_transport_publish(self):
        ai_root = BACKEND_ROOT / "ai-service"
        for module_name in list(sys.modules):
            if module_name == "app" or module_name.startswith("app."):
                del sys.modules[module_name]
        for root in (str(WORKER_ROOT), str(ai_root), str(BACKEND_ROOT)):
            while root in sys.path:
                sys.path.remove(root)
        sys.path[:0] = [str(ai_root), str(BACKEND_ROOT)]
        context_type = importlib.import_module("shared.security.execution_context").TrustedExecutionContext
        job_type = importlib.import_module("app.background_processing").AIProcessingJob
        coordinator_type = importlib.import_module("app.job_submission_service").ApplicationJobSubmissionService
        context = context_type._issue_from_authenticated_user_id(OWNER_ID)
        job = job_type.from_authenticated_context(
            job_id=JOB_ID,
            meeting_id=MEETING_ID,
            transcript_id=TRANSCRIPT_ID,
            requested_operations=["summary"],
            execution_context=context,
        )
        events = []

        class Registrar:
            async def register(self, **kwargs):
                events.append(("register", kwargs))
                return object()

        class Publisher:
            async def submit(self, submitted):
                events.append(("publish", submitted.job_id))
                return SimpleNamespace(job_id=submitted.job_id)

        receipt = await coordinator_type(Registrar(), Publisher()).submit(job)
        self.assertEqual(receipt.job_id, job.job_id)
        self.assertEqual([event[0] for event in events], ["register", "publish"])
        self.assertEqual(events[0][1]["owner_id"], OWNER_ID)


if __name__ == "__main__":
    unittest.main()
