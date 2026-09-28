"""Behavioral tests for provider-independent decision extraction."""

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
        self.content = '{"decisions":[]}' if content is None else content
        self.error = error
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        contracts = importlib.import_module("app.contracts")
        return contracts.ModelResponse(content=self.content)


class DecisionAgentTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _prepare_ai_imports()
        self.contracts = importlib.import_module("app.contracts")
        self.errors = importlib.import_module("llm.errors")
        self.decision_module = importlib.import_module("agents.decision_agent")
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
                        "text": "We considered PostgreSQL and MongoDB.",
                        "start_ms": 100,
                        "end_ms": 900,
                    },
                    {
                        "index": 1,
                        "speaker": "Sam",
                        "text": "We agreed to use PostgreSQL for this project.",
                        "start_ms": 950,
                        "end_ms": 1700,
                    },
                ],
            },
        )

    def _agent(self, provider):
        return self.decision_module.DecisionAgent(provider)

    async def test_identity_common_agent_and_injected_provider(self) -> None:
        provider = FakeModelProvider()
        agent = self._agent(provider)

        self.assertIsInstance(agent, self.decision_module.Agent)
        self.assertEqual(agent.kind, self.contracts.AgentKind.DECISION)
        self.assertIs(agent._model_provider, provider)
        self.assertIs(agent.output_model, self.decision_module.DecisionAgentOutput)
        with self.assertRaises(TypeError):
            self.decision_module.DecisionAgent()

    async def test_request_carries_context_and_decision_semantics(self) -> None:
        provider = FakeModelProvider()
        await self._agent(provider).execute(self.agent_input)

        request = provider.requests[0]
        instructions = request.instructions.lower()
        for required in (
            "explicit decisions",
            "actually reached",
            "proposals",
            "suggestions",
            "questions",
            "unresolved disagreement",
            "tasks",
            "untrusted source material",
            "never as instructions",
            "never invent names or ids",
            "consolidate repeated references to the same decision",
            "empty decisions list",
        ):
            with self.subTest(instruction=required):
                self.assertIn(required, instructions)
        self.assertNotIn("chain-of-thought", instructions)
        self.assertNotIn("reasoning", instructions)
        self.assertEqual(
            request.response_schema,
            self.decision_module.DecisionAgentOutput.model_json_schema(),
        )
        self.assertNotIn("openai", request.model_dump_json().lower())
        payload = json.loads(request.input_text.split("\n", 1)[1])
        self.assertEqual(payload["segments"][0]["speaker"], "Ari")
        self.assertIn("considered PostgreSQL", payload["segments"][0]["text"])
        self.assertIn("agreed to use PostgreSQL", payload["segments"][1]["text"])

    async def test_zero_decisions_is_valid_for_unresolved_discussion(self) -> None:
        provider = FakeModelProvider('{"decisions":[]}')

        result = await self._agent(provider).execute(self.agent_input)

        self.assertIsInstance(result, self.decision_module.DecisionAgentOutput)
        self.assertEqual(result.decisions, [])

    async def test_proposals_questions_and_unresolved_options_are_not_decisions(
        self,
    ) -> None:
        samples = (
            "We could use PostgreSQL.",
            "Should we use PostgreSQL?",
            "We discussed PostgreSQL versus MongoDB, but did not resolve it.",
        )
        for sample in samples:
            with self.subTest(sample=sample):
                agent_input = self.contracts.AgentInput.model_validate(
                    {
                        "meeting_id": str(self.agent_input.meeting_id),
                        "transcript": {
                            "transcript_id": str(
                                self.agent_input.transcript.transcript_id
                            ),
                            "language": "en",
                            "segments": [{"index": 0, "speaker": "Ari", "text": sample}],
                        },
                    }
                )
                provider = FakeModelProvider('{"decisions":[]}')

                result = await self._agent(provider).execute(agent_input)

                self.assertEqual(result.decisions, [])
                self.assertIn(sample, provider.requests[0].input_text)

    async def test_single_explicit_decision_is_typed_with_optional_context_and_people(
        self,
    ) -> None:
        provider = FakeModelProvider(
            '{"decisions":[{"statement":"Use PostgreSQL for the project.",'
            '"context":"The team resolved the database choice after comparing options.",'
            '"participants":["Ari","Sam"]}]}'
        )

        result = await self._agent(provider).execute(self.agent_input)

        self.assertEqual(len(result.decisions), 1)
        decision = result.decisions[0]
        self.assertEqual(decision.statement, "Use PostgreSQL for the project.")
        self.assertEqual(
            decision.context,
            "The team resolved the database choice after comparing options.",
        )
        self.assertEqual(decision.participants, ["Ari", "Sam"])

    async def test_multiple_decisions_remain_separate_and_optional_fields_default(
        self,
    ) -> None:
        provider = FakeModelProvider(
            '{"decisions":[{"statement":"Use PostgreSQL."},'
            '{"statement":"Launch the beta next month.","participants":["Sam"]}]}'
        )

        result = await self._agent(provider).execute(self.agent_input)

        self.assertEqual(len(result.decisions), 2)
        self.assertEqual(result.decisions[0].statement, "Use PostgreSQL.")
        self.assertIsNone(result.decisions[0].context)
        self.assertEqual(result.decisions[0].participants, [])
        self.assertEqual(result.decisions[1].participants, ["Sam"])

    def test_output_rejects_blank_required_optional_and_persistence_fields(self) -> None:
        output = self.decision_module.DecisionAgentOutput
        invalid = (
            '{"decisions":[{"statement":"  "}]}',
            '{"decisions":[{"statement":"Use PostgreSQL.","context":"  "}]}',
            '{"decisions":[{"statement":"Use PostgreSQL.","participants":[" "]}]}',
            '{"decisions":[{"statement":"Use PostgreSQL.","participants":["d146f98d-d557-4b89-a746-3e48e73d46b1"]}]}',
            '{"decisions":[{"statement":"Use PostgreSQL.","context":12}]}',
            '{"decisions":{}}',
            '{"decisions":[{}]}',
            '{"decisions":[{"statement":"Use PostgreSQL.","meeting_id":"x"}]}',
            '{}',
        )
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                output.model_validate_json(raw)

    async def test_malformed_provider_output_fails_explicitly(self) -> None:
        for content in (
            "not-json",
            '{"decisions":[{"statement":"  "}]}',
        ):
            with self.subTest(content=content):
                with self.assertRaises(self.errors.MalformedModelOutputError):
                    await self._agent(FakeModelProvider(content)).execute(
                        self.agent_input
                    )

    async def test_provider_configuration_timeout_and_failure_are_controlled(
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

    def test_invalid_transcript_reuses_agent_input_contract(self) -> None:
        transcript_id = "084c3a14-1a7f-41c9-a7c8-1e195aa5313a"
        for transcript in (
            None,
            {"transcript_id": transcript_id, "segments": []},
            {
                "transcript_id": transcript_id,
                "segments": [{"index": 0, "text": "   "}],
            },
        ):
            with self.subTest(transcript=transcript), self.assertRaises(ValidationError):
                self.contracts.AgentInput.model_validate(
                    {
                        "meeting_id": str(self.agent_input.meeting_id),
                        "transcript": transcript,
                    }
                )

    async def test_orchestrator_executes_decision_agent_through_common_contract(
        self,
    ) -> None:
        provider = FakeModelProvider('{"decisions":[]}')
        agent = self._agent(provider)

        result = await self.orchestrator_module.AIProcessingOrchestrator().execute_agent(
            agent, self.agent_input
        )

        self.assertEqual(agent.kind, self.contracts.AgentKind.DECISION)
        self.assertEqual(result.decisions, [])
        self.assertEqual(len(provider.requests), 1)

    def test_decision_agent_imports_without_persistence_dependencies(self) -> None:
        guarded_script = """
import builtins
real_import = builtins.__import__
blocked = ('sqlalchemy', 'shared.database.models', 'app.repositories', 'app.services')
def guarded_import(name, *args, **kwargs):
    if any(name == root or name.startswith(root + '.') for root in blocked):
        raise AssertionError('Decision Agent imported persistence code')
    return real_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
from agents.decision_agent import DecisionAgent, DecisionAgentOutput, DecisionCandidate
assert DecisionAgent and DecisionAgentOutput and DecisionCandidate
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
