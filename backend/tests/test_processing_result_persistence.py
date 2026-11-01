"""Tests for atomically persisting worker results to Meeting domain records."""

from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

BACKEND = Path(__file__).resolve().parents[1]
MEETING_ROOT = BACKEND / "meeting-service"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from shared.jobs.lifecycle import JobStatus, ProcessingJobService

MEETING_ID = UUID("30000000-0000-0000-0000-000000000003")
TRANSCRIPT_ID = UUID("40000000-0000-0000-0000-000000000004")
JOB_ID = UUID("50000000-0000-0000-0000-000000000005")
OWNER_ID = UUID("10000000-0000-0000-0000-000000000001")


class _ScalarResult:
    def scalar_one_or_none(self):
        return MEETING_ID

    def scalar_one(self):
        return 2


class _Session:
    def __init__(self):
        self.added = []
        self.flush_count = 0
        self.commits = 0
        self.in_transaction = False

    def add(self, value):
        self.added.append(value)

    async def execute(self, _statement):
        return _ScalarResult()

    async def scalar(self, _statement):
        return 2

    async def flush(self):
        self.flush_count += 1

    async def commit(self):
        self.commits += 1

    def begin(self):
        return _Transaction(self)


class _Transaction:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        self.session.in_transaction = True

    async def __aexit__(self, *_):
        self.session.in_transaction = False


class _LifecycleRepository:
    def __init__(self, session):
        self.session = session

    async def create_if_absent(self, record):
        self.session.record = record
        return record

    async def get_by_id(self, _job_id, *, for_update=False):
        return getattr(self.session, "record", None)

    async def update(self, record):
        self.session.record = record
        return record


def _result():
    return {
        "meeting_id": str(MEETING_ID),
        "transcript_id": str(TRANSCRIPT_ID),
        "requested_operations": ["summary", "tasks", "decisions", "follow_ups", "insights"],
        "status": "completed",
        "results": [
            {"operation": "summary", "status": "completed", "output": {
                "meeting_id": str(MEETING_ID), "content": "Summary text", "key_topics": ["delivery"],
                "model_provider": None, "model_name": None,
            }, "error": None},
            {"operation": "tasks", "status": "completed", "output": {"items": [
                {"meeting_id": str(MEETING_ID), "title": "Review plan", "description": None,
                 "assignee_id": None, "due_at": None},
            ]}, "error": None},
            {"operation": "decisions", "status": "completed", "output": {"items": [
                {"meeting_id": str(MEETING_ID), "statement": "Keep scope", "context": None,
                 "participants": []},
            ]}, "error": None},
            {"operation": "follow_ups", "status": "completed", "output": {"items": [
                {"meeting_id": str(MEETING_ID), "subject": "Meeting notes", "body_html": "<p>Notes</p>",
                 "recipients": ["person@example.com"]},
            ]}, "error": None},
            {"operation": "insights", "status": "completed", "output": {"items": [
                {"meeting_id": str(MEETING_ID), "category": "risk", "title": "Schedule risk",
                 "description": "Delivery date is at risk."},
            ]}, "error": None},
        ],
    }


def _drive(coroutine):
    try:
        return coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("Persistence test unexpectedly suspended on external I/O.")


class ProcessingResultPersistenceTests(unittest.TestCase):
    def setUp(self):
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        for root in (str(MEETING_ROOT), str(BACKEND)):
            while root in sys.path:
                sys.path.remove(root)
        sys.path[:0] = [str(MEETING_ROOT), str(BACKEND)]
        self.module = importlib.import_module("app.services.processing_result_persistence")
        self.session = _Session()
        self.record = SimpleNamespace(
            job_id=JOB_ID, meeting_id=MEETING_ID, transcript_id=TRANSCRIPT_ID,
            owner_id=OWNER_ID,
            requested_operations=["summary", "tasks", "decisions", "follow_ups", "insights"],
        )

    def test_persists_all_successful_mapped_outputs_without_committing(self):
        _drive(self.module.persist_processing_result(self.session, self.record, _result()))

        tables = [type(item).__tablename__ for item in self.session.added]
        self.assertCountEqual(tables, [
            "summaries", "tasks", "decisions", "followups", "meeting_insights",
        ])
        summary = next(item for item in self.session.added if type(item).__tablename__ == "summaries")
        task = next(item for item in self.session.added if type(item).__tablename__ == "tasks")
        followup = next(item for item in self.session.added if type(item).__tablename__ == "followups")
        self.assertEqual(summary.version, 3)
        self.assertEqual(task.assignee_id, None)
        self.assertEqual(task.due_at, None)
        self.assertEqual(followup.recipients, ["person@example.com"])
        self.assertEqual(self.session.flush_count, 1)
        self.assertEqual(self.session.commits, 0)

    def test_rejects_result_identity_mismatch_before_writing(self):
        result = _result()
        result["meeting_id"] = str(UUID("30000000-0000-0000-0000-000000000099"))
        with self.assertRaisesRegex(ValueError, "identity"):
            _drive(self.module.persist_processing_result(self.session, self.record, result))
        self.assertEqual(self.session.added, [])

    def test_failed_operation_is_not_persisted(self):
        result = _result()
        result["results"][1] = {
            "operation": "tasks", "status": "failed", "output": None,
            "error": {"code": "provider_timeout", "message": "The model provider timed out."},
        }
        _drive(self.module.persist_processing_result(self.session, self.record, result))
        self.assertNotIn("tasks", [type(item).__tablename__ for item in self.session.added])

    def test_result_persistence_is_part_of_the_terminal_lifecycle_transaction(self):
        callbacks = []

        async def persist(session, job, result):
            callbacks.append((session.in_transaction, job.job_id, result))

        lifecycle = ProcessingJobService(
            self.session,
            _LifecycleRepository(self.session),
            completed_result_persister=persist,
        )
        _drive(lifecycle.register(
            job_id=JOB_ID, meeting_id=MEETING_ID, transcript_id=TRANSCRIPT_ID,
            owner_id=OWNER_ID, requested_operations=["summary"],
        ))
        claim = _drive(lifecycle.claim(
            job_id=JOB_ID, meeting_id=MEETING_ID, transcript_id=TRANSCRIPT_ID,
            owner_id=OWNER_ID, requested_operations=["summary"],
        ))
        result = {"meeting_id": str(MEETING_ID)}
        self.assertTrue(_drive(lifecycle.complete(
            JOB_ID, claim.lease_token, status=JobStatus.COMPLETED, result=result,
        )))
        self.assertEqual(callbacks, [(True, JOB_ID, result)])
        self.assertEqual(self.session.record.status, JobStatus.COMPLETED.value)
        self.assertFalse(_drive(lifecycle.complete(
            JOB_ID, claim.lease_token, status=JobStatus.COMPLETED, result=result,
        )))
        self.assertEqual(len(callbacks), 1)

    def test_persistence_failure_does_not_transition_job_to_terminal(self):
        async def fail_persist(*_):
            raise ValueError("domain persistence failed")

        lifecycle = ProcessingJobService(
            self.session,
            _LifecycleRepository(self.session),
            completed_result_persister=fail_persist,
        )
        _drive(lifecycle.register(
            job_id=JOB_ID, meeting_id=MEETING_ID, transcript_id=TRANSCRIPT_ID,
            owner_id=OWNER_ID, requested_operations=["summary"],
        ))
        claim = _drive(lifecycle.claim(
            job_id=JOB_ID, meeting_id=MEETING_ID, transcript_id=TRANSCRIPT_ID,
            owner_id=OWNER_ID, requested_operations=["summary"],
        ))
        with self.assertRaisesRegex(ValueError, "domain persistence failed"):
            _drive(lifecycle.complete(
                JOB_ID, claim.lease_token, status=JobStatus.COMPLETED, result={},
            ))
        self.assertEqual(self.session.record.status, JobStatus.RUNNING.value)

    def test_worker_runtime_wires_meeting_persister_into_job_lifecycle(self):
        worker_root = BACKEND / "worker-service"
        for name in list(sys.modules):
            if name == "app" or name.startswith("app.") or name == "jobs" or name.startswith("jobs."):
                del sys.modules[name]
        for root in (str(MEETING_ROOT), str(worker_root), str(BACKEND)):
            while root in sys.path:
                sys.path.remove(root)
        sys.path[:0] = [str(worker_root), str(BACKEND)]
        worker_runtime = importlib.import_module("jobs.runtime")
        persister = self.module.persist_processing_result
        service_types = {
            "get_settings": lambda: SimpleNamespace(),
            "AIProcessingJob": object,
            "persist_processing_result": persister,
            "create_model_provider": object,
            "AIProcessingOrchestrator": object,
            "AIProcessingService": object,
            "AIProcessingJobExecutorService": object,
            "MeetingServiceTranscriptInputProvider": object,
            "MeetingService": object,
            "MeetingRepository": object,
            "TranscriptRepository": object,
        }
        settings = SimpleNamespace(
            background_job_verification_public_key=None,
            background_job_issuer="ai-service",
            background_job_audience="mannerai-worker",
            background_job_authorization_max_age_seconds=120,
        )
        with patch.object(worker_runtime, "_load_service_types", return_value=service_types), patch.object(
            worker_runtime, "PostgresJobLifecycle", return_value=object()
        ) as lifecycle_factory:
            worker_runtime.create_worker_job_runtime(settings)
        self.assertIs(
            lifecycle_factory.call_args.kwargs["completed_result_persister"],
            persister,
        )


if __name__ == "__main__":
    unittest.main()
