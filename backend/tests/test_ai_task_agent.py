"""Behavioral tests for provider-independent task extraction."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import unittest
from datetime import date
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
    def __init__(self, content: str | None = None, error: Exception | None = None):
        self.content = '{"tasks":[]}' if content is None else content
        self.error = error
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        contracts = importlib.import_module("app.contracts")
        return contracts.ModelResponse(content=self.content)


class TaskAgentTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _prepare_ai_imports()
        self.contracts = importlib.import_module("app.contracts")
        self.errors = importlib.import_module("llm.errors")
        self.task_module = importlib.import_module("agents.task_agent")
        self.orchestrator_module = importlib.import_module("agents.orchestrator")
        self.agent_input = self.contracts.AgentInput(
            meeting_id="d146f98d-d557-4b89-a746-3e48e73d46b1",
            transcript={
                "transcript_id": "084c3a14-1a7f-41c9-a7c8-1e195aa5313a",
                "language": "en",
                "segments": [
                    {
                        "index": 0,
                        "speaker": "Ari",
                        "text": "Ari will send the launch notes by Friday.",
                        "start_ms": 100,
                        "end_ms": 900,
                    },
                    {
                        "index": 1,
                        "speaker": "Sam",
                        "text": "I will confirm the release checklist.",
                        "start_ms": 950,
                        "end_ms": 1700,
                    },
                ],
            },
        )

    def _agent(self, provider):
        return self.task_module.TaskAgent(provider)

    async def test_identity_common_agent_and_injected_provider(self) -> None:
        provider = FakeModelProvider()
        agent = self._agent(provider)

        self.assertIsInstance(agent, self.task_module.Agent)
        self.assertEqual(agent.kind, self.contracts.AgentKind.TASK)
        self.assertIs(agent._model_provider, provider)
        self.assertIs(agent.output_model, self.task_module.TaskAgentOutput)
        with self.assertRaises(TypeError):
            self.task_module.TaskAgent()

    async def test_request_contains_transcript_and_task_specific_safe_instructions(
        self,
    ) -> None:
        provider = FakeModelProvider()
        await self._agent(provider).execute(self.agent_input)

        request = provider.requests[0]
        instructions = request.instructions.lower()
        self.assertIn("actionable tasks", instructions)
        self.assertIn("untrusted source material", instructions)
        self.assertIn("do not invent", instructions)
        self.assertIn("assignees", instructions)
        self.assertIn("deadlines", instructions)
        self.assertIn("by friday", instructions)
        self.assertIn("empty tasks list", instructions)
        self.assertNotIn("chain-of-thought", instructions)
        self.assertNotIn("reasoning", instructions)
        self.assertEqual(
            request.response_schema,
            self.task_module.TaskAgentOutput.model_json_schema(),
        )
        self.assertNotIn("openai", request.model_dump_json().lower())
        payload = json.loads(request.input_text.split("\n", 1)[1])
        self.assertEqual(payload["segments"][0]["speaker"], "Ari")
        self.assertIn("by Friday", payload["segments"][0]["text"])
        self.assertEqual(payload["segments"][0]["start_ms"], 100)

    async def test_zero_tasks_is_a_valid_structured_result(self) -> None:
        provider = FakeModelProvider('{"tasks":[]}')

        result = await self._agent(provider).execute(self.agent_input)

        self.assertIsInstance(result, self.task_module.TaskAgentOutput)
        self.assertEqual(result.tasks, [])

    async def test_single_task_supports_null_assignee_and_ambiguous_due_date(self) -> None:
        provider = FakeModelProvider(
            '{"tasks":[{"title":"Send launch notes",'
            '"description":null,"assignee_name":null,"due_date":null}]}'
        )

        result = await self._agent(provider).execute(self.agent_input)

        self.assertEqual(len(result.tasks), 1)
        task = result.tasks[0]
        self.assertEqual(task.title, "Send launch notes")
        self.assertIsNone(task.description)
        self.assertIsNone(task.assignee_name)
        self.assertIsNone(task.due_date)

    async def test_multiple_tasks_remain_distinct_and_date_is_typed(self) -> None:
        provider = FakeModelProvider(
            '{"tasks":['
            '{"title":"Send launch notes","description":"Share with the team",'
            '"assignee_name":"Ari","due_date":"2026-10-02"},'
            '{"title":"Confirm release checklist","description":null,'
            '"assignee_name":"Sam","due_date":null}'
            ']}'
        )

        result = await self._agent(provider).execute(self.agent_input)

        self.assertEqual(len(result.tasks), 2)
        self.assertEqual(result.tasks[0].assignee_name, "Ari")
        self.assertEqual(result.tasks[0].assignee_name, "Ari")
        self.assertIsInstance(result.tasks[0].due_date, date)
        self.assertEqual(result.tasks[0].due_date, date(2026, 10, 2))
        self.assertIsNone(result.tasks[1].due_date)
        self.assertIsNone(result.tasks[1].description)

    def test_output_rejects_bad_titles_types_dates_and_extra_persistence_fields(
        self,
    ) -> None:
        output = self.task_module.TaskAgentOutput
        invalid_outputs = (
            '{"tasks":[{"title":"  ","description":null,"assignee_name":null,"due_date":null}]}',
            '{"tasks":[{"title":"Ship", "description":7,"assignee_name":null,"due_date":null}]}',
            '{"tasks":[{"title":"Ship", "description":null,"assignee_name":" ","due_date":null}]}',
            '{"tasks":[{"title":"Ship", "description":null,"assignee_name":"d146f98d-d557-4b89-a746-3e48e73d46b1","due_date":null}]}',
            '{"tasks":[{"title":"Ship", "description":null,"assignee_name":null,"due_date":"2026-02-30"}]}',
            '{"tasks":[{"title":"Ship", "description":null,"assignee_name":null,"due_date":"Friday"}]}',
            '{"tasks":[{"title":"Ship", "description":null,"assignee_name":null,"due_date":null,"status":"done"}]}',
            '{"tasks":{}}',
            '{"tasks":[{}]}',
            '{}',
        )
        for raw in invalid_outputs:
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                output.model_validate_json(raw)

    async def test_malformed_provider_content_becomes_controlled_output_error(
        self,
    ) -> None:
        with self.assertRaises(self.errors.MalformedModelOutputError):
            await self._agent(FakeModelProvider("not-json")).execute(self.agent_input)

    async def test_provider_configuration_timeout_and_failure_remain_controlled(
        self,
    ) -> None:
        with self.assertRaises(self.errors.ProviderNotConfiguredError):
            await self._agent(None).execute(self.agent_input)

        for error, expected in (
            (TimeoutError(), self.errors.ModelTimeoutError),
            (
                self.errors.ModelProviderUnavailableError(),
                self.errors.ModelProviderUnavailableError,
            ),
        ):
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(expected):
                    await self._agent(FakeModelProvider(error=error)).execute(
                        self.agent_input
                    )

    def test_invalid_transcript_uses_existing_agent_input_validation(self) -> None:
        transcript_id = "084c3a14-1a7f-41c9-a7c8-1e195aa5313a"
        invalid = (
            None,
            {"transcript_id": transcript_id, "segments": []},
            {
                "transcript_id": transcript_id,
                "segments": [{"index": 0, "text": "  "}],
            },
        )
        for transcript in invalid:
            with self.subTest(transcript=transcript), self.assertRaises(ValidationError):
                self.contracts.AgentInput.model_validate(
                    {
                        "meeting_id": str(self.agent_input.meeting_id),
                        "transcript": transcript,
                    }
                )

    async def test_orchestrator_executes_task_agent_using_common_abstraction(self) -> None:
        provider = FakeModelProvider('{"tasks":[]}')
        agent = self._agent(provider)

        result = await self.orchestrator_module.AIProcessingOrchestrator().execute_agent(
            agent, self.agent_input
        )

        self.assertEqual(agent.kind, self.contracts.AgentKind.TASK)
        self.assertEqual(result.tasks, [])
        self.assertEqual(len(provider.requests), 1)

    def test_task_agent_imports_without_database_or_domain_persistence_code(self) -> None:
        guarded_script = """
import builtins
real_import = builtins.__import__
blocked = ('sqlalchemy', 'shared.database.models', 'app.repositories', 'app.services')
def guarded_import(name, *args, **kwargs):
    if any(name == root or name.startswith(root + '.') for root in blocked):
        raise AssertionError('Task Agent imported persistence code')
    return real_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
from agents.task_agent import TaskAgent, TaskAgentOutput, TaskCandidate
assert TaskAgent and TaskAgentOutput and TaskCandidate
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
