"""Unit tests for framework-neutral AI background job boundaries."""

from __future__ import annotations

import importlib
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
AI_SERVICE_ROOT = BACKEND_ROOT / "ai-service"
MEETING_ID = UUID("d146f98d-d557-4b89-a746-3e48e73d46b1")
TRANSCRIPT_ID = UUID("084c3a14-1a7f-41c9-a7c8-1e195aa5313a")


def _prepare_imports() -> None:
    for module_name in list(sys.modules):
        if any(
            module_name == package or module_name.startswith(f"{package}.")
            for package in ("app", "agents", "llm")
        ):
            del sys.modules[module_name]
    for service in ("gateway-service", "meeting-service", "ai-service"):
        root = str(BACKEND_ROOT / service)
        while root in sys.path:
            sys.path.remove(root)
    sys.path.insert(0, str(BACKEND_ROOT))
    sys.path.insert(0, str(AI_SERVICE_ROOT))


class AIBackgroundProcessingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _prepare_imports()
        self.jobs = importlib.import_module("app.background_processing")
        self.contracts = importlib.import_module("app.contracts")
        self.results = importlib.import_module("app.processing_results")
        self.transcript_schema = importlib.import_module("shared.schemas.transcript")
        self.summary_schema = importlib.import_module("shared.schemas.summary")

    def _job(self, **updates):
        values = {
            "meeting_id": MEETING_ID,
            "transcript_id": TRANSCRIPT_ID,
            "requested_operations": ["summary"],
            "context": {"project": "launch"},
        }
        values.update(updates)
        return self.jobs.AIProcessingJob(**values)

    def _transcript(self, *, meeting_id=MEETING_ID, transcript_id=TRANSCRIPT_ID):
        now = datetime(2026, 10, 2, tzinfo=timezone.utc)
        return self.transcript_schema.TranscriptInDB(
            id=str(transcript_id),
            meeting_id=str(meeting_id),
            language="en",
            segments=[
                self.transcript_schema.TranscriptSegment(
                    index=0, speaker="Ravi", text="Send the revised launch plan."
                )
            ],
            created_at=now,
            updated_at=now,
        )

    def _result(self, job, status=None, *, error_code=None):
        O = self.contracts.ProcessingOperation
        if status is None:
            status = self.contracts.ProcessingStatus.COMPLETED
        if status == self.contracts.ProcessingStatus.FAILED:
            error = self.results.ProcessingFailure(
                code=error_code or self.results.ProcessingErrorCode.PROVIDER_UNAVAILABLE,
                message="The model provider is unavailable.",
            )
            results = [
                self.results.MappedOperationResult(
                    operation=operation,
                    status=self.results.OperationStatus.FAILED,
                    error=error,
                )
                for operation in job.requested_operations
            ]
        elif status == self.contracts.ProcessingStatus.PARTIALLY_FAILED:
            results = [
                self.results.MappedOperationResult(
                    operation=O.SUMMARY,
                    status=self.results.OperationStatus.COMPLETED,
                    output=self.summary_schema.SummaryBase(
                        meeting_id=str(job.meeting_id), content="Summary", key_topics=[]
                    ),
                ),
                self.results.MappedOperationResult(
                    operation=O.TASKS,
                    status=self.results.OperationStatus.FAILED,
                    error=self.results.ProcessingFailure(
                        code=self.results.ProcessingErrorCode.MALFORMED_OUTPUT,
                        message="The model returned invalid output.",
                    ),
                ),
            ]
        else:
            results = [
                self.results.MappedOperationResult(
                    operation=operation,
                    status=self.results.OperationStatus.COMPLETED,
                    output=self.summary_schema.SummaryBase(
                        meeting_id=str(job.meeting_id), content="Summary", key_topics=[]
                    ),
                )
                for operation in job.requested_operations
            ]
        return self.results.AIProcessingResult(
            meeting_id=job.meeting_id,
            transcript_id=job.transcript_id,
            requested_operations=job.requested_operations,
            status=status,
            results=results,
        )

    def _executor(self, *, result=None, side_effect=None, transcript=None):
        processing_service = AsyncMock()
        if side_effect is not None:
            processing_service.process.side_effect = side_effect
        else:
            processing_service.process.return_value = result
        resolver = AsyncMock()
        resolver.get_transcript.return_value = transcript or self._transcript()
        executor = self.jobs.AIProcessingJobExecutorService(
            processing_service=processing_service,
            transcript_resolver=resolver,
        )
        return executor, processing_service, resolver

    def test_job_contract_validates_ids_operations_and_starts_queued(self):
        job = self._job(requested_operations=["insights", "summary", "insights"])
        self.assertIsInstance(job.job_id, UUID)
        self.assertEqual(job.status, self.jobs.AIProcessingJobStatus.QUEUED)
        self.assertTrue(job.created_at.tzinfo)
        self.assertEqual(
            job.requested_operations,
            [self.contracts.ProcessingOperation.INSIGHTS,
             self.contracts.ProcessingOperation.SUMMARY],
        )

    def test_missing_invalid_ids_and_operations_are_rejected(self):
        with self.assertRaises(ValidationError):
            self._job(meeting_id="not-a-uuid")
        with self.assertRaises(ValidationError):
            self.jobs.AIProcessingJob(
                transcript_id=TRANSCRIPT_ID, requested_operations=["summary"]
            )
        with self.assertRaises(ValidationError):
            self._job(requested_operations=[])
        with self.assertRaises(ValidationError):
            self._job(requested_operations=["unknown"])

    def test_status_transition_graph_is_explicit(self):
        instant = datetime(2026, 10, 2, tzinfo=timezone.utc)
        job = self._job(created_at=instant)
        running = job.start(at=instant)
        completed = running.finish(self._result(job), at=instant)
        failed_from_queued = job.fail(self.jobs.JobFailureCode.INVALID_INPUT, at=instant)

        self.assertEqual(running.status, self.jobs.AIProcessingJobStatus.RUNNING)
        self.assertEqual(completed.status, self.jobs.AIProcessingJobStatus.COMPLETED)
        self.assertEqual(completed.job_id, job.job_id)
        self.assertEqual(failed_from_queued.status, self.jobs.AIProcessingJobStatus.FAILED)
        self.assertEqual(failed_from_queued.failure.code, self.jobs.JobFailureCode.INVALID_INPUT)
        with self.assertRaises(self.jobs.InvalidJobTransitionError):
            job.finish(self._result(job), at=instant)
        with self.assertRaises(self.jobs.InvalidJobTransitionError):
            completed.start(at=instant)
        with self.assertRaises(self.jobs.InvalidJobTransitionError):
            completed.fail(self.jobs.JobFailureCode.EXECUTION_FAILED, at=instant)

    async def test_executor_delegates_to_processing_service_and_preserves_identity(self):
        job = self._job()
        executor, processing_service, resolver = self._executor(result=self._result(job))

        finished = await executor.execute(job)

        self.assertEqual(finished.status, self.jobs.AIProcessingJobStatus.COMPLETED)
        self.assertEqual(finished.job_id, job.job_id)
        self.assertEqual(finished.meeting_id, MEETING_ID)
        self.assertEqual(finished.transcript_id, TRANSCRIPT_ID)
        resolver.get_transcript.assert_awaited_once_with(MEETING_ID, TRANSCRIPT_ID)
        processing_service.process.assert_awaited_once()
        request, transcript = processing_service.process.await_args.args
        self.assertEqual(request.meeting_id, MEETING_ID)
        self.assertEqual(request.transcript_id, TRANSCRIPT_ID)
        self.assertEqual(request.requested_operations, job.requested_operations)
        self.assertEqual(request.context, job.context)
        self.assertEqual(transcript.id, str(TRANSCRIPT_ID))

    async def test_missing_meeting_or_transcript_is_a_controlled_failure(self):
        job = self._job()
        executor, processing_service, resolver = self._executor()
        resolver.get_transcript.side_effect = self.jobs.TranscriptNotFoundError()

        finished = await executor.execute(job)

        self.assertEqual(finished.status, self.jobs.AIProcessingJobStatus.FAILED)
        self.assertEqual(finished.failure.code, self.jobs.JobFailureCode.TRANSCRIPT_NOT_FOUND)
        self.assertEqual(
            finished.failure.message,
            "The requested transcript is unavailable.",
        )
        processing_service.process.assert_not_awaited()

    async def test_transcript_for_another_meeting_is_rejected_before_ai(self):
        job = self._job()
        executor, processing_service, _ = self._executor(
            transcript=self._transcript(meeting_id=UUID(int=99))
        )

        finished = await executor.execute(job)

        self.assertEqual(finished.status, self.jobs.AIProcessingJobStatus.FAILED)
        self.assertEqual(finished.failure.code, self.jobs.JobFailureCode.INVALID_INPUT)
        processing_service.process.assert_not_awaited()

    async def test_unavailable_transcript_has_controlled_safe_failure(self):
        job = self._job()
        executor, processing_service, resolver = self._executor()
        resolver.get_transcript.side_effect = self.jobs.TranscriptUnavailableError(
            "database details must not escape"
        )

        finished = await executor.execute(job)

        self.assertEqual(finished.status, self.jobs.AIProcessingJobStatus.FAILED)
        self.assertEqual(
            finished.failure.code, self.jobs.JobFailureCode.TRANSCRIPT_UNAVAILABLE
        )
        self.assertNotIn("database", finished.failure.message)
        processing_service.process.assert_not_awaited()

    async def test_existing_normalizer_preserves_order_speaker_timestamps_and_language(self):
        job = self._job()
        transcript = self._transcript()
        transcript.segments = [
            self.transcript_schema.TranscriptSegment(
                index=2, speaker="Maya", text="Second point", start_ms=200, end_ms=300
            ),
            self.transcript_schema.TranscriptSegment(
                index=1, speaker="Ravi", text="First point", start_ms=100, end_ms=180
            ),
        ]
        transcript.language = "hi"
        orchestrator = AsyncMock()
        orchestrator.process.return_value = self.results.ProcessingResult(
            meeting_id=job.meeting_id,
            transcript_id=job.transcript_id,
            requested_operations=job.requested_operations,
            status=self.contracts.ProcessingStatus.COMPLETED,
            results=[
                self.results.OperationResult(
                    operation=self.contracts.ProcessingOperation.SUMMARY,
                    status=self.results.OperationStatus.COMPLETED,
                    output=importlib.import_module("agents.summary_agent").SummaryAgentOutput(
                        content="Two points were discussed.", key_topics=["planning"]
                    ),
                )
            ],
        )
        processing_service = importlib.import_module("app.processing_service").AIProcessingService(
            orchestrator
        )
        resolver = AsyncMock()
        resolver.get_transcript.return_value = transcript
        executor = self.jobs.AIProcessingJobExecutorService(processing_service, resolver)

        finished = await executor.execute(job)

        self.assertEqual(finished.status, self.jobs.AIProcessingJobStatus.COMPLETED)
        orchestrator.process.assert_awaited_once()
        request, agent_input = orchestrator.process.await_args.args
        self.assertEqual(request.meeting_id, job.meeting_id)
        self.assertEqual(request.transcript_id, job.transcript_id)
        self.assertEqual(agent_input.meeting_id, job.meeting_id)
        self.assertEqual(agent_input.transcript.transcript_id, job.transcript_id)
        self.assertEqual(agent_input.transcript.language, "hi")
        self.assertEqual(
            [(segment.index, segment.speaker, segment.text,
              segment.start_ms, segment.end_ms)
             for segment in agent_input.transcript.segments],
            [(1, "Ravi", "First point", 100, 180),
             (2, "Maya", "Second point", 200, 300)],
        )

    async def test_invalid_transcript_content_does_not_reach_orchestrator(self):
        job = self._job()
        transcript = self._transcript()
        transcript.segments = []
        orchestrator = AsyncMock()
        processing_service = importlib.import_module("app.processing_service").AIProcessingService(
            orchestrator
        )
        resolver = AsyncMock()
        resolver.get_transcript.return_value = transcript
        executor = self.jobs.AIProcessingJobExecutorService(processing_service, resolver)

        finished = await executor.execute(job)

        self.assertEqual(finished.status, self.jobs.AIProcessingJobStatus.FAILED)
        self.assertEqual(finished.failure.code, self.jobs.JobFailureCode.INVALID_INPUT)
        orchestrator.process.assert_not_awaited()

    async def test_partial_processing_result_becomes_partially_failed_job(self):
        job = self._job(requested_operations=["summary", "tasks"])
        executor, _, _ = self._executor(
            result=self._result(job, self.contracts.ProcessingStatus.PARTIALLY_FAILED)
        )
        finished = await executor.execute(job)
        self.assertEqual(finished.status, self.jobs.AIProcessingJobStatus.PARTIALLY_FAILED)
        self.assertIsNone(finished.failure)
        self.assertEqual(finished.processing_result.status, self.contracts.ProcessingStatus.PARTIALLY_FAILED)

    async def test_total_ai_failure_and_mapping_failure_are_typed_job_failures(self):
        for processing_code, job_code in (
            (self.results.ProcessingErrorCode.PROVIDER_UNAVAILABLE,
             self.jobs.JobFailureCode.AI_PROCESSING_FAILED),
            (self.results.ProcessingErrorCode.DOMAIN_MAPPING_FAILED,
             self.jobs.JobFailureCode.DOMAIN_MAPPING_FAILED),
            (self.results.ProcessingErrorCode.INVALID_INPUT,
             self.jobs.JobFailureCode.INVALID_INPUT),
        ):
            with self.subTest(job_code=job_code):
                job = self._job()
                executor, _, _ = self._executor(
                    result=self._result(
                        job,
                        self.contracts.ProcessingStatus.FAILED,
                        error_code=processing_code,
                    )
                )
                finished = await executor.execute(job)
                self.assertEqual(finished.status, self.jobs.AIProcessingJobStatus.FAILED)
                self.assertEqual(finished.failure.code, job_code)
                self.assertNotIn("provider", finished.failure.message.lower())
                self.assertEqual(finished.processing_result.status, self.contracts.ProcessingStatus.FAILED)

    async def test_invalid_transcript_identity_fails_job_without_calling_ai_service(self):
        job = self._job()
        executor, processing_service, _ = self._executor(
            result=self._result(job), transcript=self._transcript(transcript_id=UUID(int=7))
        )
        finished = await executor.execute(job)
        self.assertEqual(finished.status, self.jobs.AIProcessingJobStatus.FAILED)
        self.assertEqual(finished.failure.code, self.jobs.JobFailureCode.INVALID_INPUT)
        processing_service.process.assert_not_awaited()

    async def test_unexpected_execution_failure_is_sanitized_and_isolated(self):
        first = self._job()
        second = self._job(meeting_id=UUID(int=31), transcript_id=UUID(int=32))
        executor, processing_service, resolver = self._executor(
            result=self._result(second)
        )
        resolver.get_transcript.side_effect = [
            RuntimeError("api-key=secret"),
            self._transcript(meeting_id=UUID(int=31), transcript_id=UUID(int=32)),
        ]
        processing_service.process.return_value = self._result(second)

        first_result = await executor.execute(first)
        second_result = await executor.execute(second)

        self.assertEqual(first_result.status, self.jobs.AIProcessingJobStatus.FAILED)
        self.assertEqual(first_result.failure.code, self.jobs.JobFailureCode.EXECUTION_FAILED)
        self.assertNotIn("secret", str(first_result.model_dump(mode="json")))
        self.assertEqual(second_result.status, self.jobs.AIProcessingJobStatus.COMPLETED)
        self.assertEqual(second_result.job_id, second.job_id)

    async def test_executor_rejects_nonqueued_job_and_result_identity_mismatch(self):
        job = self._job()
        executor, processing_service, _ = self._executor(result=self._result(job))
        with self.assertRaises(self.jobs.InvalidJobTransitionError):
            await executor.execute(job.start())

        mismatched_result = self._result(job).model_copy(
            update={"transcript_id": UUID(int=99)}
        )
        processing_service.process.return_value = mismatched_result
        finished = await executor.execute(job)
        self.assertEqual(finished.status, self.jobs.AIProcessingJobStatus.FAILED)
        self.assertEqual(finished.failure.code, self.jobs.JobFailureCode.EXECUTION_FAILED)

    async def test_in_process_submission_is_fifo_and_returns_queued_receipts(self):
        class RecordingExecutor:
            def __init__(inner_self):
                inner_self.jobs = []

            async def execute(inner_self, job):
                inner_self.jobs.append(job)
                return job.start().fail(
                    self.jobs.JobFailureCode.EXECUTION_FAILED
                )

        executor = RecordingExecutor()
        submission = self.jobs.InProcessJobSubmissionPort(executor)
        first, second = self._job(), self._job(meeting_id=UUID(int=41), transcript_id=UUID(int=42))
        first_receipt = await submission.submit(first)
        second_receipt = await submission.submit(second)

        self.assertEqual(first_receipt.job_id, first.job_id)
        self.assertEqual(first_receipt.status, self.jobs.AIProcessingJobStatus.QUEUED)
        self.assertEqual(second_receipt.job_id, second.job_id)
        self.assertEqual(submission.pending_count, 2)

        first_result = await submission.run_next()
        second_result = await submission.run_next()
        self.assertEqual([job.job_id for job in executor.jobs], [first.job_id, second.job_id])
        self.assertEqual(first_result.job_id, first.job_id)
        self.assertEqual(second_result.job_id, second.job_id)
        self.assertEqual(submission.pending_count, 0)
        with self.assertRaises(self.jobs.NoQueuedJobError):
            await submission.run_next()

    async def test_submission_queue_copies_jobs_and_rejects_nonqueued_submission(self):
        class RecordingExecutor:
            async def execute(inner_self, job):
                inner_self.received = job
                return job.start().fail(self.jobs.JobFailureCode.EXECUTION_FAILED)

        executor = RecordingExecutor()
        submission = self.jobs.InProcessJobSubmissionPort(executor)
        job = self._job()
        await submission.submit(job)
        job.context["project"] = "mutated-after-submit"
        result = await submission.run_next()
        self.assertEqual(executor.received.context["project"], "launch")
        self.assertEqual(result.failure.code, self.jobs.JobFailureCode.EXECUTION_FAILED)
        with self.assertRaises(self.jobs.InvalidJobTransitionError):
            await submission.submit(result)


if __name__ == "__main__":
    unittest.main()
