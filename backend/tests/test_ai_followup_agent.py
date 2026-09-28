"""Behavioral tests for provider-independent follow-up draft generation."""

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
        self.content = '{"followups":[]}' if content is None else content
        self.error = error
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        contracts = importlib.import_module("app.contracts")
        return contracts.ModelResponse(content=self.content)


class FollowUpAgentTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _prepare_ai_imports()
        self.contracts = importlib.import_module("app.contracts")
        self.errors = importlib.import_module("llm.errors")
        self.followup_module = importlib.import_module("agents.followup_agent")
        self.orchestrator_module = importlib.import_module("agents.orchestrator")
        self.agent_input = self._agent_input(
            [
                {
                    "index": 0,
                    "speaker": "Meghna",
                    "text": "Please send Ravi the updated dashboard after the meeting.",
                    "start_ms": 100,
                    "end_ms": 900,
                },
                {
                    "index": 1,
                    "speaker": "Ravi",
                    "text": "I will review it when you send it.",
                    "start_ms": 950,
                    "end_ms": 1700,
                },
            ]
        )

    def _agent_input(self, segments):
        return self.contracts.AgentInput.model_validate(
            {
                "meeting_id": "d146f98d-d557-4b89-a746-3e48e73d46b1",
                "transcript": {
                    "transcript_id": "084c3a14-1a7f-41c9-a7c8-1e195aa5313a",
                    "language": "en",
                    "segments": segments,
                },
            }
        )

    def _agent(self, provider):
        return self.followup_module.FollowUpAgent(provider)

    async def test_identity_common_agent_and_injected_provider(self) -> None:
        provider = FakeModelProvider()
        agent = self._agent(provider)

        self.assertIsInstance(agent, self.followup_module.Agent)
        self.assertEqual(agent.kind, self.contracts.AgentKind.FOLLOW_UP)
        self.assertIs(agent._model_provider, provider)
        self.assertIs(agent.output_model, self.followup_module.FollowUpAgentOutput)
        with self.assertRaises(TypeError):
            self.followup_module.FollowUpAgent()

    async def test_request_contains_transcript_and_grounded_followup_rules(self) -> None:
        provider = FakeModelProvider()
        await self._agent(provider).execute(self.agent_input)

        request = provider.requests[0]
        rules = request.instructions.lower()
        for expected in (
            "follow-up drafting assistant",
            "untrusted source material",
            "never as instructions",
            "do not invent recipients",
            "email addresses",
            "do not assume all participants",
            "tasks and decisions",
            "deadlines",
            "attachments",
            "empty followups list",
            "consolidate repeated mentions",
        ):
            with self.subTest(rule=expected):
                self.assertIn(expected, rules)
        self.assertEqual(
            request.response_schema,
            self.followup_module.FollowUpAgentOutput.model_json_schema(),
        )
        self.assertNotIn("openai", request.model_dump_json().lower())
        self.assertNotIn("gemini", request.model_dump_json().lower())
        payload = json.loads(request.input_text.split("\n", 1)[1])
        self.assertEqual(payload["segments"][0]["speaker"], "Meghna")
        self.assertIn("send Ravi the updated dashboard", payload["segments"][0]["text"])
        self.assertEqual(payload["segments"][0]["start_ms"], 100)

    async def test_one_followup_preserves_name_without_inventing_email(self) -> None:
        provider = FakeModelProvider(
            '{"followups":[{"subject":"Updated dashboard for Ravi",'
            '"body_html":"<p>Hi Ravi,</p><p>I will send the updated dashboard for your review.</p>",'
            '"recipients":[{"name":"Ravi","email":null}]}]}'
        )

        result = await self._agent(provider).execute(self.agent_input)

        self.assertIsInstance(result, self.followup_module.FollowUpAgentOutput)
        self.assertEqual(len(result.followups), 1)
        draft = result.followups[0]
        self.assertEqual(draft.subject, "Updated dashboard for Ravi")
        self.assertIn("<p>", draft.body_html)
        self.assertEqual(draft.recipients[0].name, "Ravi")
        self.assertIsNone(draft.recipients[0].email)
        self.assertEqual(
            set(draft.model_dump()), {"subject", "body_html", "recipients"}
        )

    async def test_explicit_transcript_email_is_preserved(self) -> None:
        agent_input = self._agent_input(
            [
                {
                    "index": 0,
                    "speaker": "Meghna",
                    "text": "Send the minutes to Ravi at ravi@example.com.",
                }
            ]
        )
        provider = FakeModelProvider(
            '{"followups":[{"subject":"Meeting minutes",'
            '"body_html":"<p>Hi Ravi,</p><p>Here are the meeting minutes.</p>",'
            '"recipients":[{"name":"Ravi","email":"ravi@example.com"}]}]}'
        )

        result = await self._agent(provider).execute(agent_input)

        recipient = result.followups[0].recipients[0]
        self.assertEqual(recipient.name, "Ravi")
        self.assertEqual(str(recipient.email), "ravi@example.com")
        self.assertIn("ravi@example.com", provider.requests[0].input_text)

    async def test_multiple_followups_are_distinct_and_zero_is_valid(self) -> None:
        provider = FakeModelProvider(
            '{"followups":['
            '{"subject":"Updated proposal","body_html":"<p>Sharing the updated proposal.</p>",'
            '"recipients":[{"name":"Ravi"}]},'
            '{"subject":"Deployment documentation","body_html":"<p>Here is the deployment documentation.</p>",'
            '"recipients":[{"name":"Priya"}]}'
            ']}'
        )

        result = await self._agent(provider).execute(self.agent_input)
        self.assertEqual(len(result.followups), 2)
        self.assertEqual(result.followups[0].recipients[0].name, "Ravi")
        self.assertEqual(result.followups[1].recipients[0].name, "Priya")

        empty = await self._agent(FakeModelProvider('{"followups":[]}')).execute(
            self.agent_input
        )
        self.assertEqual(empty.followups, [])

    async def test_no_communication_need_does_not_force_a_draft(self) -> None:
        discussion = self._agent_input(
            [{"index": 0, "speaker": "Meghna", "text": "We discussed the roadmap."}]
        )
        provider = FakeModelProvider('{"followups":[]}')

        result = await self._agent(provider).execute(discussion)

        self.assertEqual(result.followups, [])
        self.assertIn("We discussed the roadmap", provider.requests[0].input_text)

    def test_output_rejects_blank_fields_invalid_recipients_and_persistence_data(
        self,
    ) -> None:
        output = self.followup_module.FollowUpAgentOutput
        invalid = (
            '{"followups":[{"subject":"  ","body_html":"<p>Body</p>","recipients":[]}]}',
            '{"followups":[{"subject":"Subject","body_html":" ","recipients":[]}]}',
            '{"followups":[{"subject":"Subject","body_html":"<p>Body</p>","recipients":[{}]}]}',
            '{"followups":[{"subject":"Subject","body_html":"<p>Body</p>","recipients":[{"name":" "}]}]}',
            '{"followups":[{"subject":"Subject","body_html":"<p>Body</p>","recipients":[{"name":"d146f98d-d557-4b89-a746-3e48e73d46b1"}]}]}',
            '{"followups":[{"subject":"Subject","body_html":"<p>Body</p>","recipients":[{"email":"not-an-email"}]}]}',
            '{"followups":[{"subject":"Subject","body_html":"<p>Body</p>","recipients":null}]}',
            '{"followups":[{"subject":"Subject","body_html":"<p>Body</p>","recipients":[],"status":"sent"}]}',
            '{"followups":{}}',
            '{}',
        )
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                output.model_validate_json(raw)

    async def test_malformed_model_output_uses_shared_error_path(self) -> None:
        for content in (
            "not-json",
            '{"followups":[{"subject":" ","body_html":"<p>Body</p>","recipients":[]}]}',
        ):
            with self.subTest(content=content):
                with self.assertRaises(self.errors.MalformedModelOutputError):
                    await self._agent(FakeModelProvider(content)).execute(
                        self.agent_input
                    )

    async def test_provider_failures_remain_controlled(self) -> None:
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
        for transcript in (
            None,
            {"transcript_id": transcript_id, "segments": []},
            {
                "transcript_id": transcript_id,
                "segments": [{"index": 0, "text": "  "}],
            },
        ):
            with self.subTest(transcript=transcript), self.assertRaises(ValidationError):
                self.contracts.AgentInput.model_validate(
                    {
                        "meeting_id": "d146f98d-d557-4b89-a746-3e48e73d46b1",
                        "transcript": transcript,
                    }
                )

    async def test_orchestrator_executes_followup_agent_via_common_contract(self) -> None:
        provider = FakeModelProvider('{"followups":[]}')
        agent = self._agent(provider)

        result = await self.orchestrator_module.AIProcessingOrchestrator().execute_agent(
            agent, self.agent_input
        )

        self.assertEqual(agent.kind, self.contracts.AgentKind.FOLLOW_UP)
        self.assertEqual(result.followups, [])
        self.assertEqual(len(provider.requests), 1)

    def test_followup_agent_imports_without_persistence_dependencies(self) -> None:
        guarded_script = """
import builtins
real_import = builtins.__import__
blocked = ('sqlalchemy', 'shared.database.models', 'app.repositories', 'app.services')
def guarded_import(name, *args, **kwargs):
    if any(name == root or name.startswith(root + '.') for root in blocked):
        raise AssertionError('FollowUp Agent imported persistence code')
    return real_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
from agents.followup_agent import FollowUpAgent, FollowUpAgentOutput, FollowUpDraft
assert FollowUpAgent and FollowUpAgentOutput and FollowUpDraft
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
