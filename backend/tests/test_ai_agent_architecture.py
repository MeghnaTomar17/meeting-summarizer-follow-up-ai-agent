"""Common AI agent contract, transcript boundary, and orchestration tests."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import unittest
from pathlib import Path

from pydantic import BaseModel, ValidationError

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


class TestAgentOutput(BaseModel):
    label: str


class FakeModelProvider:
    def __init__(self, content: str = '{"label":"validated"}', error=None):
        self.content = content
        self.error = error
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        contracts = importlib.import_module("app.contracts")
        return contracts.ModelResponse(content=self.content)


class FakeSummaryAgentFactory:
    @staticmethod
    def create(agent_base, provider):
        contracts = importlib.import_module("app.contracts")

        class FakeSummaryAgent(agent_base.Agent[TestAgentOutput]):
            @property
            def kind(self):
                return contracts.AgentKind.SUMMARY

            @property
            def output_model(self):
                return TestAgentOutput

            def build_model_request(self, agent_input):
                return contracts.ModelRequest(
                    instructions="Return the requested typed output.",
                    input_text=" ".join(
                        segment.text for segment in agent_input.transcript.segments
                    ),
                )

        return FakeSummaryAgent(provider)


class AgentArchitectureTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _prepare_ai_imports()
        self.contracts = importlib.import_module("app.contracts")
        self.errors = importlib.import_module("llm.errors")
        self.agent_module = importlib.import_module("agents.base")
        self.orchestrator_module = importlib.import_module("agents.orchestrator")
        self.agent_input = self.contracts.AgentInput(
            meeting_id="d146f98d-d557-4b89-a746-3e48e73d46b1",
            transcript={
                "transcript_id": "084c3a14-1a7f-41c9-a7c8-1e195aa5313a",
                "language": "en",
                "segments": [
                    {"index": 0, "speaker": "Ari", "text": "Confirm deployment."},
                    {"index": 1, "speaker": "Sam", "text": "I will follow up."},
                ],
            },
            meeting_context={"project": "release"},
        )

    def _fake_agent(self, provider):
        return FakeSummaryAgentFactory.create(self.agent_module, provider)

    async def test_fake_agent_satisfies_common_contract_and_has_controlled_identity(
        self,
    ) -> None:
        provider = FakeModelProvider()
        agent = self._fake_agent(provider)

        self.assertIsInstance(agent, self.agent_module.Agent)
        self.assertEqual(agent.kind, self.contracts.AgentKind.SUMMARY)
        self.assertIs(agent._model_provider, provider)

    def test_agent_identity_is_a_controlled_existing_enum(self) -> None:
        self.assertEqual(
            {kind.value for kind in self.contracts.AgentKind},
            {"summary", "task", "decision", "follow_up", "insight"},
        )
        self.assertIsNot(self.contracts.AgentKind, self.contracts.ProcessingOperation)
        with self.assertRaises(ValueError):
            self.contracts.AgentKind("unknown")

    def test_agent_input_requires_nonempty_transcript_content(self) -> None:
        with self.assertRaises(ValidationError):
            self.contracts.AgentInput.model_validate(
                {"meeting_id": str(self.agent_input.meeting_id)}
            )
        invalid_transcript = {
            "meeting_id": str(self.agent_input.meeting_id),
            "transcript": {
                "transcript_id": str(self.agent_input.transcript.transcript_id),
                "segments": [],
            },
        }
        with self.assertRaises(ValidationError):
            self.contracts.AgentInput.model_validate(invalid_transcript)
        invalid_transcript["transcript"]["segments"] = [
            {"index": 0, "text": "  "}
        ]
        with self.assertRaises(ValidationError):
            self.contracts.AgentInput.model_validate(invalid_transcript)

    async def test_agent_builds_neutral_request_and_validates_typed_output(self) -> None:
        provider = FakeModelProvider()
        agent = self._fake_agent(provider)

        output = await agent.execute(self.agent_input)

        self.assertIsInstance(output, TestAgentOutput)
        self.assertEqual(output.label, "validated")
        self.assertEqual(
            provider.requests[0].instructions,
            "Return the requested typed output.",
        )
        self.assertEqual(
            provider.requests[0].input_text,
            "Confirm deployment. I will follow up.",
        )
        self.assertEqual(
            provider.requests[0].response_schema,
            TestAgentOutput.model_json_schema(),
        )

    async def test_agent_uses_shared_malformed_output_failure(self) -> None:
        provider = FakeModelProvider('{"label": ["malformed-sensitive-value"]}')
        agent = self._fake_agent(provider)

        with self.assertRaises(self.errors.MalformedModelOutputError) as raised:
            await agent.execute(self.agent_input)

        self.assertNotIn("malformed-sensitive-value", str(raised.exception))

    async def test_agent_preserves_safe_provider_failure(self) -> None:
        provider = FakeModelProvider(
            error=self.errors.ModelProviderUnavailableError()
        )
        agent = self._fake_agent(provider)

        with self.assertRaises(self.errors.ModelProviderUnavailableError) as raised:
            await agent.execute(self.agent_input)

        self.assertEqual(str(raised.exception), "The model provider is unavailable.")

    async def test_orchestrator_delegates_to_agent_contract_without_model_work(
        self,
    ) -> None:
        class NoWorkAgent(self.agent_module.Agent[TestAgentOutput]):
            @property
            def kind(self):
                return self_kind

            @property
            def output_model(self):
                return TestAgentOutput

            def build_model_request(self, _agent_input):
                raise AssertionError("delegation test must not build a model request")

            async def execute(self, agent_input):
                self.received = agent_input
                return TestAgentOutput(label="delegated")

        self_kind = self.contracts.AgentKind.INSIGHT
        agent = NoWorkAgent(FakeModelProvider())
        orchestrator = self.orchestrator_module.AIProcessingOrchestrator()

        output = await orchestrator.execute_agent(agent, self.agent_input)

        self.assertEqual(agent.kind, self_kind)
        self.assertIs(agent.received, self.agent_input)
        self.assertEqual(output.label, "delegated")

    def test_agent_layer_imports_without_provider_sdks_or_database(self) -> None:
        guarded_import_script = """
import builtins
real_import = builtins.__import__
blocked = ('openai', 'google', 'sqlalchemy')
def guarded_import(name, *args, **kwargs):
    if any(name == root or name.startswith(root + '.') for root in blocked):
        raise AssertionError('agent layer imported a provider SDK or database ORM')
    return real_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
from agents.base import Agent
from app.contracts import AgentInput, AgentKind
assert Agent and AgentInput and AgentKind
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
