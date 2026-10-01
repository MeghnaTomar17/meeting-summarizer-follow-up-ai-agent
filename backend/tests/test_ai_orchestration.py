"""Deterministic end-to-end tests for AI operation orchestration."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
AI_SERVICE_ROOT = BACKEND_ROOT / "ai-service"
SERVICE_NAMES = (
    "gateway-service",
    "meeting-service",
    "ai-service",
    "search-service",
    "worker-service",
)


def _prepare_ai_imports() -> None:
    for module_name in list(sys.modules):
        if any(
            module_name == package or module_name.startswith(f"{package}.")
            for package in ("app", "agents", "llm", "pipelines")
        ):
            del sys.modules[module_name]
    for service_name in SERVICE_NAMES:
        service_root = str(BACKEND_ROOT / service_name)
        while service_root in sys.path:
            sys.path.remove(service_root)
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    sys.path.insert(0, str(AI_SERVICE_ROOT))


class FakeModelProvider:
    """Choose deterministic provider content from the requested output schema."""

    responses = {
        "SummaryAgentOutput": '{"content":"Meeting summary.","key_topics":["planning"]}',
        "TaskAgentOutput": '{"tasks":[{"title":"Send notes","description":null,"assignee_name":null,"due_date":null}]}',
        "DecisionAgentOutput": '{"decisions":[{"statement":"Use the agreed plan.","context":null,"participants":[]}]}',
        "FollowUpAgentOutput": '{"followups":[{"subject":"Meeting notes","body_html":"<p>Here are the notes.</p>","recipients":[{"name":"Ravi","email":null}]}]}',
        "InsightAgentOutput": '{"insights":[{"category":"risk","title":"Delivery timing risk","description":"The transcript states delivery may be late."}]}',
    }

    def __init__(self, *, failures=None, malformed=()):
        self.failures = failures or {}
        self.malformed = set(malformed)
        self.requests = []
        self.requested_outputs = []

    async def generate(self, request):
        self.requests.append(request)
        output_name = request.response_schema["title"]
        self.requested_outputs.append(output_name)
        if output_name in self.failures:
            raise self.failures[output_name]
        contracts = importlib.import_module("app.contracts")
        content = (
            "not-json"
            if output_name in self.malformed
            else self.responses[output_name]
        )
        return contracts.ModelResponse(content=content)


class AIOrchestrationTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _prepare_ai_imports()
        self.contracts = importlib.import_module("app.contracts")
        self.results = importlib.import_module("app.processing_results")
        self.errors = importlib.import_module("llm.errors")
        self.orchestrator_module = importlib.import_module("agents.orchestrator")
        self.meeting_id = "d146f98d-d557-4b89-a746-3e48e73d46b1"
        self.transcript_id = "084c3a14-1a7f-41c9-a7c8-1e195aa5313a"
        self.request = self.contracts.ProcessingRequest(
            meeting_id=self.meeting_id,
            transcript_id=self.transcript_id,
            requested_operations=[
                "summary",
                "tasks",
                "decisions",
                "follow_ups",
                "insights",
            ],
        )
        self.agent_input = self.contracts.AgentInput.model_validate(
            {
                "meeting_id": self.meeting_id,
                "transcript": {
                    "transcript_id": self.transcript_id,
                    "language": "en",
                    "segments": [
                        {"index": 0, "speaker": "Ravi", "text": "Send the notes."},
                        {
                            "index": 1,
                            "speaker": "Meghna",
                            "text": "The vendor could be late.",
                        },
                    ],
                },
            }
        )

    async def test_each_requested_operation_routes_to_its_typed_agent_output(self):
        provider = FakeModelProvider()
        orchestrator = self.orchestrator_module.AIProcessingOrchestrator(provider)

        result = await orchestrator.process(self.request, self.agent_input)

        output_models = (
            importlib.import_module("agents.summary_agent").SummaryAgentOutput,
            importlib.import_module("agents.task_agent").TaskAgentOutput,
            importlib.import_module("agents.decision_agent").DecisionAgentOutput,
            importlib.import_module("agents.followup_agent").FollowUpAgentOutput,
            importlib.import_module("agents.insight_agent").InsightAgentOutput,
        )
        self.assertEqual(result.status, self.contracts.ProcessingStatus.COMPLETED)
        self.assertEqual(
            [type(item.output) for item in result.results], list(output_models)
        )
        self.assertEqual(
            provider.requested_outputs,
            [model.__name__ for model in output_models],
        )
        self.assertIs(orchestrator._model_provider, provider)

    async def test_multiple_operations_execute_sequentially_in_requested_order(self):
        provider = FakeModelProvider()
        request = self.contracts.ProcessingRequest(
            meeting_id=self.meeting_id,
            transcript_id=self.transcript_id,
            requested_operations=["insights", "summary", "tasks"],
        )

        result = await self.orchestrator_module.AIProcessingOrchestrator(
            provider
        ).process(request, self.agent_input)

        self.assertEqual(
            [item.operation for item in result.results],
            [
                self.contracts.ProcessingOperation.INSIGHTS,
                self.contracts.ProcessingOperation.SUMMARY,
                self.contracts.ProcessingOperation.TASKS,
            ],
        )
        self.assertEqual(
            provider.requested_outputs,
            ["InsightAgentOutput", "SummaryAgentOutput", "TaskAgentOutput"],
        )

    def test_duplicate_operations_are_deduplicated_preserving_first_order(self):
        request = self.contracts.ProcessingRequest(
            meeting_id=self.meeting_id,
            transcript_id=self.transcript_id,
            requested_operations=["tasks", "summary", "tasks", "summary"],
        )

        self.assertEqual(
            request.requested_operations,
            [
                self.contracts.ProcessingOperation.TASKS,
                self.contracts.ProcessingOperation.SUMMARY,
            ],
        )

    async def test_result_preserves_identity_and_separate_agent_inputs(self):
        provider = FakeModelProvider()

        result = await self.orchestrator_module.AIProcessingOrchestrator(
            provider
        ).process(self.request, self.agent_input)

        self.assertEqual(str(result.meeting_id), self.meeting_id)
        self.assertEqual(str(result.transcript_id), self.transcript_id)
        self.assertEqual(len(provider.requests), len(self.request.requested_operations))
        transcript_payloads = [
            json.loads(request.input_text.split("\n", 1)[1])
            for request in provider.requests
        ]
        self.assertTrue(all(payload == transcript_payloads[0] for payload in transcript_payloads))
        self.assertTrue(
            all("Meeting summary." not in request.input_text for request in provider.requests)
        )

    async def test_partial_failure_preserves_successes_and_safe_failure(self):
        provider = FakeModelProvider(malformed={"TaskAgentOutput"})
        request = self.contracts.ProcessingRequest(
            meeting_id=self.meeting_id,
            transcript_id=self.transcript_id,
            requested_operations=["summary", "tasks", "insights"],
        )

        result = await self.orchestrator_module.AIProcessingOrchestrator(
            provider
        ).process(request, self.agent_input)

        self.assertEqual(result.status, self.contracts.ProcessingStatus.PARTIALLY_FAILED)
        self.assertIsNotNone(result.results[0].output)
        self.assertEqual(
            result.results[1].error.code,
            self.results.ProcessingErrorCode.MALFORMED_OUTPUT,
        )
        self.assertEqual(
            result.results[2].output.insights[0].category.value,
            "risk",
        )

    async def test_all_failures_produce_failed_aggregate(self):
        provider = FakeModelProvider(
            failures={
                "SummaryAgentOutput": self.errors.ModelProviderUnavailableError(),
                "TaskAgentOutput": self.errors.ModelProviderUnavailableError(),
            }
        )
        request = self.contracts.ProcessingRequest(
            meeting_id=self.meeting_id,
            transcript_id=self.transcript_id,
            requested_operations=["summary", "tasks"],
        )

        result = await self.orchestrator_module.AIProcessingOrchestrator(
            provider
        ).process(request, self.agent_input)

        self.assertEqual(result.status, self.contracts.ProcessingStatus.FAILED)
        self.assertTrue(all(item.output is None for item in result.results))
        self.assertTrue(
            all(
                item.error.code == self.results.ProcessingErrorCode.PROVIDER_UNAVAILABLE
                for item in result.results
            )
        )

    async def test_unconfigured_provider_is_reported_per_operation(self):
        request = self.contracts.ProcessingRequest(
            meeting_id=self.meeting_id,
            transcript_id=self.transcript_id,
            requested_operations=["summary"],
        )

        result = await self.orchestrator_module.AIProcessingOrchestrator().process(
            request, self.agent_input
        )

        self.assertEqual(result.status, self.contracts.ProcessingStatus.FAILED)
        self.assertEqual(
            result.results[0].error.code,
            self.results.ProcessingErrorCode.PROVIDER_NOT_CONFIGURED,
        )

    async def test_provider_exception_details_are_not_exposed(self):
        provider = FakeModelProvider(
            failures={"SummaryAgentOutput": RuntimeError("provider secret payload")}
        )
        request = self.contracts.ProcessingRequest(
            meeting_id=self.meeting_id,
            transcript_id=self.transcript_id,
            requested_operations=["summary"],
        )

        result = await self.orchestrator_module.AIProcessingOrchestrator(
            provider
        ).process(request, self.agent_input)

        failure = result.results[0].error
        self.assertEqual(failure.code, self.results.ProcessingErrorCode.UNEXPECTED_FAILURE)
        self.assertNotIn("secret", failure.message)
        self.assertNotIn("secret", str(result.model_dump(mode="json")))

    def test_empty_or_unknown_operations_fail_request_validation(self):
        with self.assertRaises(ValidationError):
            self.contracts.ProcessingRequest(
                meeting_id=self.meeting_id,
                transcript_id=self.transcript_id,
                requested_operations=[],
            )
        with self.assertRaises(ValidationError):
            self.contracts.ProcessingRequest.model_validate(
                {
                    "meeting_id": self.meeting_id,
                    "transcript_id": self.transcript_id,
                    "requested_operations": ["future_operation"],
                }
            )

    async def test_mismatched_processing_and_agent_identity_fails_before_execution(
        self,
    ):
        provider = FakeModelProvider()
        request = self.contracts.ProcessingRequest(
            meeting_id=self.meeting_id,
            transcript_id="ed991f92-22a1-43f2-a280-66239a24c014",
            requested_operations=["summary"],
        )
        with self.assertRaises(ValueError):
            await self.orchestrator_module.AIProcessingOrchestrator(provider).process(
                request, self.agent_input
            )
        self.assertEqual(provider.requests, [])

    def test_aggregate_contract_rejects_output_operation_mismatch(self):
        summary = importlib.import_module("agents.summary_agent").SummaryAgentOutput(
            content="Summary.", key_topics=[]
        )
        with self.assertRaises(ValidationError):
            self.results.OperationResult(
                operation=self.contracts.ProcessingOperation.TASKS,
                status=self.results.OperationStatus.COMPLETED,
                output=summary,
            )

    def test_aggregate_contract_rejects_duplicate_requested_operations(self):
        with self.assertRaises(ValidationError):
            self.results.ProcessingResult(
                meeting_id=self.meeting_id,
                transcript_id=self.transcript_id,
                requested_operations=[
                    self.contracts.ProcessingOperation.SUMMARY,
                    self.contracts.ProcessingOperation.SUMMARY,
                ],
                status=self.contracts.ProcessingStatus.FAILED,
                results=[
                    self.results.OperationResult(
                        operation=self.contracts.ProcessingOperation.SUMMARY,
                        status=self.results.OperationStatus.FAILED,
                        error=self.results.ProcessingFailure(
                            code=self.results.ProcessingErrorCode.MALFORMED_OUTPUT,
                            message="The model returned invalid output.",
                        ),
                    ),
                    self.results.OperationResult(
                        operation=self.contracts.ProcessingOperation.SUMMARY,
                        status=self.results.OperationStatus.FAILED,
                        error=self.results.ProcessingFailure(
                            code=self.results.ProcessingErrorCode.MALFORMED_OUTPUT,
                            message="The model returned invalid output.",
                        ),
                    ),
                ],
            )

    def test_orchestration_import_has_no_database_or_provider_sdk_dependency(self):
        guarded_script = """
import builtins
real_import = builtins.__import__
blocked = ('sqlalchemy', 'openai', 'google', 'httpx', 'requests')
def guarded_import(name, *args, **kwargs):
    if any(name == root or name.startswith(root + '.') for root in blocked):
        raise AssertionError('Orchestration imported database/provider/network code')
    return real_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
from agents.orchestrator import AIProcessingOrchestrator
from app.processing_results import ProcessingResult
assert AIProcessingOrchestrator and ProcessingResult
"""
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            (str(AI_SERVICE_ROOT), str(BACKEND_ROOT))
        )
        result = subprocess.run(
            [sys.executable, "-c", guarded_script],
            cwd=BACKEND_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
