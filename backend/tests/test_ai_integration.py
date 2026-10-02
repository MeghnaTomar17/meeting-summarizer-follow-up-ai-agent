"""Application-path integration tests for deterministic AI processing."""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

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


class DeterministicModelProvider:
    """Test-only provider returning configured JSON through ModelProvider."""

    def __init__(self, responses=None, *, failures=None, malformed=()) -> None:
        self.responses = dict(responses or {})
        self.failures = dict(failures or {})
        self.malformed = set(malformed)
        self.requests = []
        self.requested_models = []

    async def generate(self, request):
        self.requests.append(request)
        output_name = request.response_schema["title"]
        self.requested_models.append(output_name)
        if output_name in self.failures:
            raise self.failures[output_name]
        if output_name in self.malformed:
            content = "{not valid json"
        else:
            content = self.responses[output_name]
        response_type = getattr(self, "response_type", None)
        if response_type is None:
            response_type = importlib.import_module("app.contracts").ModelResponse
        return response_type(content=content)


class AIApplicationIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _prepare_imports()
        self.contracts = importlib.import_module("app.contracts")
        self.jobs = importlib.import_module("app.background_processing")
        self.results = importlib.import_module("app.processing_results")
        self.service_module = importlib.import_module("app.processing_service")
        self.orchestrator_module = importlib.import_module("agents.orchestrator")
        self.transcript_schema = importlib.import_module("shared.schemas.transcript")
        self.summary_agent = importlib.import_module("agents.summary_agent")
        self.task_agent = importlib.import_module("agents.task_agent")
        self.decision_agent = importlib.import_module("agents.decision_agent")
        self.followup_agent = importlib.import_module("agents.followup_agent")
        self.insight_agent = importlib.import_module("agents.insight_agent")
        self.provider_errors = importlib.import_module("llm.errors")

    def _transcript(self):
        segment = self.transcript_schema.TranscriptSegment
        now = datetime(2026, 10, 2, tzinfo=timezone.utc)
        # Deliberately supplied out of order to exercise the real normalization path.
        return self.transcript_schema.TranscriptInDB(
            id=str(TRANSCRIPT_ID),
            meeting_id=str(MEETING_ID),
            language="en",
            segments=[
                segment(index=2, speaker="Meghna", text="The vendor may miss Friday.", start_ms=12000, end_ms=15000),
                segment(index=0, speaker="Ravi", text="We need to finish the launch plan.", start_ms=0, end_ms=4000),
                segment(index=1, speaker="Meghna", text="Ravi will send the revised plan by Thursday.", start_ms=5000, end_ms=11000),
                segment(index=3, speaker="Ravi", text="We agreed to keep the current launch date.", start_ms=16000, end_ms=20000),
                segment(index=4, speaker="Meghna", text="I will email the partner with the updated plan.", start_ms=21000, end_ms=25000),
                segment(index=5, speaker="Ravi", text="The handoff checklist is still missing an owner.", start_ms=26000, end_ms=30000),
                segment(index=6, speaker="Meghna", text="The room was a little cold today.", start_ms=31000, end_ms=34000),
            ],
            created_at=now,
            updated_at=now,
        )

    def _request(self, operations=None):
        if operations is None:
            operations = ["summary", "tasks", "decisions", "follow_ups", "insights"]
        return self.contracts.ProcessingRequest(
            meeting_id=MEETING_ID,
            transcript_id=TRANSCRIPT_ID,
            requested_operations=operations,
            context={"project": "launch"},
        )

    def _provider(self, *, failures=None, malformed=(), responses=None):
        defaults = {
            "SummaryAgentOutput": json.dumps({
                "content": "The team confirmed the launch plan and identified a vendor timing risk.",
                "key_topics": ["launch plan", "vendor timing"],
            }),
            "TaskAgentOutput": json.dumps({
                "tasks": [{"title": "Send the revised launch plan", "description": None,
                           "assignee_name": "Ravi", "due_date": None}],
            }),
            "DecisionAgentOutput": json.dumps({
                "decisions": [{"statement": "Keep the current launch date.",
                               "context": None, "participants": ["Ravi", "Meghna"]}],
            }),
            "FollowUpAgentOutput": json.dumps({
                "followups": [{"subject": "Updated launch plan",
                               "body_html": "<p>I will send the updated plan.</p>",
                               "recipients": [{"name": "Partner team", "email": "partner@example.com"}]}],
            }),
            "InsightAgentOutput": json.dumps({
                "insights": [{"category": "risk", "title": "Vendor timing risk",
                              "description": "The vendor may miss Friday."}],
            }),
        }
        defaults.update(responses or {})
        return DeterministicModelProvider(defaults, failures=failures, malformed=malformed)

    def _service(self, provider):
        orchestrator = self.orchestrator_module.AIProcessingOrchestrator(provider)
        return self.service_module.AIProcessingService(orchestrator)

    def _background_application(self, provider):
        """Connect the real AI path to MeetingService without service-package collisions."""
        provider.response_type = self.contracts.ModelResponse
        ai_service = self._service(provider)

        # Each backend service has an ``app`` package. Keep the already-imported AI
        # objects alive, then load MeetingService and its provider from their own root.
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        for service in ("gateway-service", "meeting-service", "ai-service"):
            root = str(BACKEND_ROOT / service)
            while root in sys.path:
                sys.path.remove(root)
        sys.path.insert(0, str(BACKEND_ROOT / "meeting-service"))

        meeting_service_module = importlib.import_module("app.services.meeting_service")
        transcript_provider_module = importlib.import_module(
            "app.services.transcript_input_provider"
        )
        models = importlib.import_module("shared.database.models.meeting")
        transcript_models = importlib.import_module("shared.database.models.transcript")
        now = datetime(2026, 10, 2, tzinfo=timezone.utc)
        meeting = models.Meeting(
            id=MEETING_ID,
            organization_id=UUID(int=55),
            created_by=UUID("10000000-0000-0000-0000-000000000001"),
            title="Launch planning",
            status=models.MeetingStatus.PENDING,
        )
        meeting.created_at = now
        meeting.updated_at = now
        transcript = transcript_models.Transcript(
            id=TRANSCRIPT_ID,
            meeting_id=MEETING_ID,
            language="en",
            segments=[
                {"index": 1, "speaker": "Meghna", "text": "Ravi will send the revised plan by Thursday.", "start_ms": 5000, "end_ms": 11000},
                {"index": 0, "speaker": "Ravi", "text": "We need to finish the launch plan.", "start_ms": 0, "end_ms": 4000},
            ],
        )
        transcript.created_at = now
        transcript.updated_at = now
        meeting_repository = MagicMock()
        meeting_repository.get_by_id = AsyncMock(return_value=meeting)
        transcript_repository = MagicMock()
        transcript_repository.get_by_meeting_id = AsyncMock(return_value=transcript)
        session = MagicMock()
        service = meeting_service_module.MeetingService(
            session, meeting_repository, transcript_repository
        )
        transcript_provider = transcript_provider_module.MeetingServiceTranscriptInputProvider(service)
        return ai_service, service, transcript_provider, session, meeting_repository, transcript_repository

    def _trusted_context(self, user_id=None):
        context_module = importlib.import_module("shared.security.execution_context")
        return context_module.TrustedExecutionContext._issue_from_authenticated_user_id(
            user_id or UUID("10000000-0000-0000-0000-000000000001")
        )

    def _background_job(self, operations, context):
        return self.jobs.AIProcessingJob.from_authenticated_context(
            meeting_id=MEETING_ID,
            transcript_id=TRANSCRIPT_ID,
            requested_operations=operations,
            execution_context=context,
            context={"project": "launch"},
        )

    async def test_phase8_fifo_to_typed_ai_result_through_meeting_ownership_path(self):
        provider = self._provider()
        ai_service, _, transcript_provider, session, meetings, transcripts = self._background_application(provider)
        ai_service.process = AsyncMock(wraps=ai_service.process)
        context = self._trusted_context()
        job = self._background_job(["tasks", "summary"], context)
        executor = self.jobs.AIProcessingJobExecutorService(ai_service, transcript_provider)
        submission = self.jobs.InProcessJobSubmissionPort(executor)

        receipt = await submission.submit(job)
        finished = await submission.run_next()

        self.assertEqual(receipt.job_id, job.job_id)
        self.assertEqual(finished.job_id, job.job_id)
        self.assertEqual(finished.meeting_id, MEETING_ID)
        self.assertEqual(finished.transcript_id, TRANSCRIPT_ID)
        self.assertEqual(finished.execution_context_id, context.context_id)
        self.assertEqual(finished.status, self.jobs.AIProcessingJobStatus.COMPLETED)
        ai_service.process.assert_awaited_once()
        self.assertEqual([item.operation.value for item in finished.processing_result.results], ["tasks", "summary"])
        self.assertEqual(provider.requested_models, ["TaskAgentOutput", "SummaryAgentOutput"])
        self.assertEqual(finished.processing_result.results[0].output.items[0].title, "Send the revised launch plan")
        self.assertEqual(finished.processing_result.results[1].output.content, "The team confirmed the launch plan and identified a vendor timing risk.")

        normalized = json.loads(provider.requests[0].input_text.split("\n", 1)[1])
        self.assertEqual(normalized["transcript_id"], str(TRANSCRIPT_ID))
        self.assertEqual(normalized["language"], "en")
        self.assertEqual([segment["index"] for segment in normalized["segments"]], [0, 1])
        self.assertEqual(normalized["segments"][0]["speaker"], "Ravi")
        self.assertEqual(normalized["segments"][0]["start_ms"], 0)
        meetings.get_by_id.assert_awaited_once_with(MEETING_ID)
        transcripts.get_by_meeting_id.assert_awaited_once_with(MEETING_ID)
        session.commit.assert_not_called()
        self.assertEqual(submission.pending_count, 0)
        with self.assertRaises(self.jobs.NoQueuedJobError):
            await submission.run_next()

    async def test_phase8_real_ai_partial_failure_keeps_success_and_job_status(self):
        provider_errors = importlib.import_module("llm.errors")
        provider = self._provider(
            failures={"TaskAgentOutput": provider_errors.ModelTimeoutError()}
        )
        ai_service, _, transcript_provider, session, _, _ = self._background_application(provider)
        job = self._background_job(["summary", "tasks"], self._trusted_context())
        executor = self.jobs.AIProcessingJobExecutorService(ai_service, transcript_provider)
        submission = self.jobs.InProcessJobSubmissionPort(executor)
        await submission.submit(job)

        finished = await submission.run_next()

        self.assertEqual(finished.status, self.jobs.AIProcessingJobStatus.PARTIALLY_FAILED)
        self.assertEqual(finished.processing_result.status, self.contracts.ProcessingStatus.PARTIALLY_FAILED)
        self.assertEqual([item.status.value for item in finished.processing_result.results], ["completed", "failed"])
        self.assertEqual(finished.processing_result.results[0].output.content, "The team confirmed the launch plan and identified a vendor timing risk.")
        self.assertEqual(finished.processing_result.results[1].error.code.value, "provider_timeout")
        self.assertIsNone(finished.failure)
        session.commit.assert_not_called()

    async def test_phase8_real_ai_total_failure_is_sanitized_and_unpersisted(self):
        provider_errors = importlib.import_module("llm.errors")
        provider = self._provider(failures={
            "SummaryAgentOutput": provider_errors.ModelTimeoutError(),
            "TaskAgentOutput": provider_errors.ModelTimeoutError(),
        })
        ai_service, _, transcript_provider, session, _, _ = self._background_application(provider)
        job = self._background_job(["summary", "tasks"], self._trusted_context())
        executor = self.jobs.AIProcessingJobExecutorService(ai_service, transcript_provider)
        finished = await executor.execute(job)

        self.assertEqual(finished.status, self.jobs.AIProcessingJobStatus.FAILED)
        self.assertEqual(finished.failure.code, self.jobs.JobFailureCode.AI_PROCESSING_FAILED)
        self.assertEqual(finished.processing_result.status, self.contracts.ProcessingStatus.FAILED)
        self.assertTrue(all(item.output is None for item in finished.processing_result.results))
        self.assertNotIn("timeout", finished.failure.message.lower())
        self.assertEqual(len(provider.requests), 2)
        session.commit.assert_not_called()

    async def test_phase8_wrong_owner_is_rejected_before_real_ai_provider(self):
        provider = self._provider()
        ai_service, _, transcript_provider, session, meetings, transcripts = self._background_application(provider)
        job = self._background_job(
            ["summary"], self._trusted_context(UUID("20000000-0000-0000-0000-000000000002"))
        )
        executor = self.jobs.AIProcessingJobExecutorService(ai_service, transcript_provider)
        finished = await executor.execute(job)

        self.assertEqual(finished.status, self.jobs.AIProcessingJobStatus.FAILED)
        self.assertEqual(finished.failure.code, self.jobs.JobFailureCode.EXECUTION_FAILED)
        self.assertNotIn("owner", finished.failure.message.lower())
        meetings.get_by_id.assert_awaited_once_with(MEETING_ID)
        transcripts.get_by_meeting_id.assert_not_awaited()
        self.assertEqual(provider.requests, [])
        session.commit.assert_not_called()

    async def test_real_service_orchestrator_agents_provider_and_mappers_cover_all_operations(self):
        provider = self._provider()
        result = await self._service(provider).process(self._request(), self._transcript())
        O = self.contracts.ProcessingOperation
        expected_order = [O.SUMMARY, O.TASKS, O.DECISIONS, O.FOLLOW_UPS, O.INSIGHTS]
        outputs = [item.output for item in result.results]

        self.assertEqual(result.status, self.contracts.ProcessingStatus.COMPLETED)
        self.assertEqual(result.requested_operations, expected_order)
        self.assertEqual([item.operation for item in result.results], expected_order)
        self.assertEqual(provider.requested_models, [
            "SummaryAgentOutput", "TaskAgentOutput", "DecisionAgentOutput",
            "FollowUpAgentOutput", "InsightAgentOutput",
        ])
        self.assertEqual(
            [type(item) for item in outputs],
            [
                importlib.import_module("shared.schemas.summary").SummaryBase,
                self.service_module.TaskDomainInputs,
                self.service_module.DecisionDomainInputs,
                self.service_module.FollowupDomainInputs,
                self.service_module.InsightDomainInputs,
            ],
        )
        self.assertEqual(outputs[0].meeting_id, str(MEETING_ID))
        self.assertEqual([item.meeting_id for item in outputs[1].items], [str(MEETING_ID)])
        self.assertEqual([item.meeting_id for item in outputs[2].items], [str(MEETING_ID)])
        self.assertEqual([item.meeting_id for item in outputs[3].items], [str(MEETING_ID)])
        self.assertEqual([item.meeting_id for item in outputs[4].items], [str(MEETING_ID)])
        self.assertEqual(result.meeting_id, MEETING_ID)
        self.assertEqual(result.transcript_id, TRANSCRIPT_ID)
        self.assertEqual(outputs[1].items[0].assignee_id, None)
        self.assertEqual(outputs[3].items[0].recipients, ["partner@example.com"])
        self.assertEqual(outputs[4].items[0].category.value, "risk")

        transcript_payload = json.loads(provider.requests[0].input_text.split("\n", 1)[1])
        self.assertEqual(transcript_payload["transcript_id"], str(TRANSCRIPT_ID))
        self.assertEqual(transcript_payload["language"], "en")
        self.assertEqual([item["index"] for item in transcript_payload["segments"]], list(range(7)))
        self.assertEqual(transcript_payload["segments"][0]["speaker"], "Ravi")
        self.assertEqual(transcript_payload["segments"][0]["start_ms"], 0)
        self.assertEqual(transcript_payload["segments"][0]["end_ms"], 4000)
        self.assertEqual(transcript_payload["segments"][6]["text"], "The room was a little cold today.")

    async def test_empty_collections_remain_empty_domain_inputs(self):
        outputs = {
            "TaskAgentOutput": json.dumps({"tasks": []}),
            "DecisionAgentOutput": json.dumps({"decisions": []}),
            "FollowUpAgentOutput": json.dumps({"followups": []}),
            "InsightAgentOutput": json.dumps({"insights": []}),
        }
        request = self._request(["tasks", "decisions", "follow_ups", "insights"])
        result = await self._service(self._provider(responses=outputs)).process(request, self._transcript())
        self.assertEqual(result.status, self.contracts.ProcessingStatus.COMPLETED)
        self.assertEqual([item.output.items for item in result.results], [[], [], [], []])

    async def test_one_provider_failure_is_operation_level_partial_failure(self):
        request = self._request(["summary", "tasks", "insights"])
        provider = self._provider(failures={"TaskAgentOutput": self.provider_errors.ModelTimeoutError()})
        result = await self._service(provider).process(request, self._transcript())
        self.assertEqual(result.status, self.contracts.ProcessingStatus.PARTIALLY_FAILED)
        self.assertEqual([item.status for item in result.results], ["completed", "failed", "completed"])
        self.assertEqual(result.results[1].error.code, self.results.ProcessingErrorCode.PROVIDER_TIMEOUT)
        self.assertEqual(result.results[1].error.message, "The model request timed out.")

    async def test_malformed_model_output_is_typed_safe_operation_failure(self):
        provider = self._provider(malformed={"DecisionAgentOutput"})
        result = await self._service(provider).process(
            self._request(["summary", "decisions", "insights"]), self._transcript()
        )
        self.assertEqual(result.status, self.contracts.ProcessingStatus.PARTIALLY_FAILED)
        self.assertEqual(result.results[1].error.code, self.results.ProcessingErrorCode.MALFORMED_OUTPUT)
        self.assertNotIn("not valid json", str(result.model_dump(mode="json")))

    async def test_non_default_order_and_duplicate_semantics_are_preserved(self):
        request = self._request(["insights", "tasks", "summary", "insights", "decisions", "follow_ups"])
        provider = self._provider()
        result = await self._service(provider).process(request, self._transcript())
        expected = ["insights", "tasks", "summary", "decisions", "follow_ups"]
        self.assertEqual([item.operation.value for item in result.results], expected)
        self.assertEqual(provider.requested_models, [
            "InsightAgentOutput", "TaskAgentOutput", "SummaryAgentOutput",
            "DecisionAgentOutput", "FollowUpAgentOutput",
        ])

    async def test_unsafe_task_date_and_name_only_followup_fail_without_fabrication(self):
        unsafe = {
            "TaskAgentOutput": json.dumps({"tasks": [{"title": "Send plan", "description": None,
                "assignee_name": "Ravi", "due_date": "2026-10-08"}]}),
            "FollowUpAgentOutput": json.dumps({"followups": [{"subject": "Plan", "body_html": "<p>Plan</p>",
                "recipients": [{"name": "Partner team", "email": None}]}]}),
        }
        result = await self._service(self._provider(responses=unsafe)).process(
            self._request(["tasks", "follow_ups"]), self._transcript()
        )
        self.assertEqual(result.status, self.contracts.ProcessingStatus.FAILED)
        for item in result.results:
            self.assertEqual(item.status, "failed")
            self.assertEqual(item.error.code, self.results.ProcessingErrorCode.DOMAIN_MAPPING_FAILED)
            self.assertIsNone(item.output)
            self.assertNotIn("2026-10-08", item.error.message)
            self.assertNotIn("@", item.error.message)

    async def test_provider_cannot_replace_trusted_result_identity(self):
        # Model contracts have no identity fields; mapped records take meeting_id
        # exclusively from ProcessingRequest and aggregate transcript identity too.
        result = await self._service(self._provider()).process(self._request(), self._transcript())
        self.assertEqual(result.meeting_id, MEETING_ID)
        self.assertEqual(result.transcript_id, TRANSCRIPT_ID)
        for operation in result.results:
            if operation.operation == "summary":
                self.assertEqual(operation.output.meeting_id, str(MEETING_ID))
            else:
                self.assertTrue(all(record.meeting_id == str(MEETING_ID) for record in operation.output.items))

    async def test_processing_path_has_no_database_or_repository_side_effects(self):
        # The service/orchestrator path should remain loadable without importing
        # persistence modules. Guard imports in a subprocess-like fresh module set.
        provider = self._provider()
        for module_name in list(sys.modules):
            if module_name == "shared.database" or module_name.startswith("shared.database."):
                del sys.modules[module_name]
        with patch.dict(sys.modules, {"shared.database": None, "sqlalchemy": None}):
            result = await self._service(provider).process(
                self._request(["summary", "insights"]), self._transcript()
            )
        self.assertEqual(result.status, self.contracts.ProcessingStatus.COMPLETED)
        self.assertNotIn("shared.database", sys.modules)
        self.assertNotIn("meeting_service.app.repositories", sys.modules)

    async def test_task_assignee_name_is_not_promoted_to_identity(self):
        result = await self._service(self._provider()).process(
            self._request(["tasks"]), self._transcript()
        )
        task = result.results[0].output.items[0]
        self.assertIsNone(task.assignee_id)
        self.assertFalse(hasattr(task, "assignee_name"))


if __name__ == "__main__":
    unittest.main()
