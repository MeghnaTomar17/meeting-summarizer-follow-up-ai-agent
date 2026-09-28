"""Behavioral tests for the provider-independent Summary Agent."""

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
    def __init__(self, content: str | None = None, error: Exception | None = None):
        self.content = (
            '{"content":"Discussed launch readiness.","key_topics":["launch readiness"]}'
            if content is None
            else content
        )
        self.error = error
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        contracts = importlib.import_module("app.contracts")
        return contracts.ModelResponse(content=self.content)


class SummaryAgentTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _prepare_ai_imports()
        self.contracts = importlib.import_module("app.contracts")
        self.errors = importlib.import_module("llm.errors")
        self.summary_module = importlib.import_module("agents.summary_agent")
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
                        "text": "We will launch on Friday.",
                        "start_ms": 100,
                        "end_ms": 900,
                    },
                    {
                        "index": 1,
                        "speaker": "Sam",
                        "text": "I will confirm readiness.",
                        "start_ms": 950,
                        "end_ms": 1700,
                    },
                ],
            },
        )

    def _agent(self, provider):
        return self.summary_module.SummaryAgent(provider)

    async def test_identity_output_and_injected_provider(self) -> None:
        provider = FakeModelProvider()
        agent = self._agent(provider)

        self.assertIsInstance(agent, self.summary_module.Agent)
        self.assertEqual(agent.kind, self.contracts.AgentKind.SUMMARY)
        self.assertIs(agent._model_provider, provider)
        self.assertIs(agent.output_model, self.summary_module.SummaryAgentOutput)
        with self.assertRaises(TypeError):
            self.summary_module.SummaryAgent()

    async def test_transcript_metadata_reaches_provider_neutral_request(self) -> None:
        provider = FakeModelProvider()
        agent = self._agent(provider)

        await agent.execute(self.agent_input)

        request = provider.requests[0]
        self.assertIn("summarize", request.instructions.lower())
        self.assertIn("do not invent facts", request.instructions.lower())
        self.assertIn("not instructions", request.instructions.lower())
        self.assertNotIn("reasoning", request.instructions.lower())
        self.assertEqual(
            request.response_schema,
            self.summary_module.SummaryAgentOutput.model_json_schema(),
        )
        self.assertNotIn("openai", request.model_dump_json().lower())
        self.assertNotIn("gemini", request.model_dump_json().lower())
        payload = json.loads(request.input_text.split("\n", 1)[1])
        self.assertEqual(payload["language"], "en")
        self.assertEqual(payload["segments"][0]["speaker"], "Ari")
        self.assertEqual(payload["segments"][0]["start_ms"], 100)
        self.assertEqual(payload["segments"][1]["text"], "I will confirm readiness.")
        self.assertIn("source material only", request.input_text)

    async def test_valid_structured_response_becomes_typed_output(self) -> None:
        provider = FakeModelProvider(
            '{"content":"The team plans a Friday launch and will confirm readiness.",'
            '"key_topics":["launch timing","readiness"]}'
        )

        result = await self._agent(provider).execute(self.agent_input)

        self.assertIsInstance(result, self.summary_module.SummaryAgentOutput)
        self.assertEqual(
            result.content,
            "The team plans a Friday launch and will confirm readiness.",
        )
        self.assertEqual(result.key_topics, ["launch timing", "readiness"])
        self.assertEqual(
            provider.requests[0].response_schema,
            self.summary_module.SummaryAgentOutput.model_json_schema(),
        )
        self.assertEqual(set(result.model_dump()), {"content", "key_topics"})

    def test_output_rejects_blank_content_topics_and_persistence_fields(self) -> None:
        output = self.summary_module.SummaryAgentOutput
        for payload in (
            {"content": "  ", "key_topics": []},
            {"content": "A summary", "key_topics": [" "]},
            {"content": "A summary", "key_topics": [], "version": 1},
            {"content": "A summary"},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                output.model_validate(payload)

    async def test_malformed_and_missing_content_fail_through_shared_validation(self) -> None:
        malformed = self._agent(FakeModelProvider("not-json"))
        with self.assertRaises(self.errors.MalformedModelOutputError):
            await malformed.execute(self.agent_input)

        missing_content = self._agent(FakeModelProvider('{"key_topics":[]}'))
        with self.assertRaises(self.errors.MalformedModelOutputError):
            await missing_content.execute(self.agent_input)

    async def test_provider_not_configured_and_failures_are_controlled(self) -> None:
        with self.assertRaises(self.errors.ProviderNotConfiguredError):
            await self._agent(None).execute(self.agent_input)

        cases = (
            (TimeoutError(), self.errors.ModelTimeoutError),
            (
                self.errors.ModelProviderUnavailableError(),
                self.errors.ModelProviderUnavailableError,
            ),
        )
        for error, expected in cases:
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(expected):
                    await self._agent(FakeModelProvider(error=error)).execute(
                        self.agent_input
                    )

    def test_empty_missing_and_whitespace_transcripts_follow_input_contract(self) -> None:
        for transcript in (
            None,
            {"transcript_id": "084c3a14-1a7f-41c9-a7c8-1e195aa5313a", "segments": []},
            {
                "transcript_id": "084c3a14-1a7f-41c9-a7c8-1e195aa5313a",
                "segments": [{"index": 0, "text": "  "}],
            },
        ):
            with self.subTest(transcript=transcript), self.assertRaises(ValidationError):
                self.contracts.AgentInput.model_validate(
                    {
                        "meeting_id": str(self.agent_input.meeting_id),
                        "transcript": transcript,
                    }
                )

    async def test_orchestrator_executes_summary_through_common_agent_contract(self) -> None:
        provider = FakeModelProvider()
        agent = self._agent(provider)
        orchestrator = self.orchestrator_module.AIProcessingOrchestrator()

        output = await orchestrator.execute_agent(agent, self.agent_input)

        self.assertIsInstance(output, self.summary_module.SummaryAgentOutput)
        self.assertEqual(len(provider.requests), 1)

    def test_summary_agent_imports_without_orm_or_persistence_dependencies(self) -> None:
        guarded_import_script = """
import builtins
real_import = builtins.__import__
blocked = ('sqlalchemy', 'shared.database.models', 'app.repositories', 'app.services')
def guarded_import(name, *args, **kwargs):
    if any(name == root or name.startswith(root + '.') for root in blocked):
        raise AssertionError('Summary Agent imported persistence code')
    return real_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
from agents.summary_agent import SummaryAgent, SummaryAgentOutput
assert SummaryAgent and SummaryAgentOutput
"""
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            (str(AI_SERVICE_ROOT), str(BACKEND_ROOT))
        )
        result = subprocess.run(
            [sys.executable, "-c", guarded_import_script],
            cwd=BACKEND_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
