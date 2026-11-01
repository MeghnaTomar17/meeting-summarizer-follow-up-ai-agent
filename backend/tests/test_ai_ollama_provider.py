"""Mock-only tests for Ollama provider selection and fail-closed budgeting."""

from __future__ import annotations

import importlib
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
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


class FakeCounter:
    def __init__(self, counts: dict[str, tuple[int, bool]]) -> None:
        self.counts = counts
        self.requests = []

    def count_request_tokens(self, metadata, request):
        self.requests.append((metadata, request))
        value, exact = self.counts[request.input_text]
        token_count = importlib.import_module("llm.token_budget").TokenCount
        return token_count(value=value, exact=exact)


class OllamaProviderTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _prepare_ai_imports()
        self.contracts = importlib.import_module("app.contracts")
        self.errors = importlib.import_module("llm.errors")
        self.registry = importlib.import_module("llm.model_registry")
        self.budget = importlib.import_module("llm.token_budget")
        self.provider_module = importlib.import_module("llm.ollama_client")
        self.factory = importlib.import_module("llm.provider_factory")
        self.settings_module = importlib.import_module("app.config.settings")
        self.metadata = self.registry.resolve_model("ollama", "llama3.2:3b")
        self.schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
        self.request = self.contracts.ModelRequest(
            instructions="System instructions",
            input_text='{"segments":[{"index":7,"text":"hello"}]}',
            response_schema=self.schema,
            budget_scope="summary",
        )

    def _verified_assessment(self, provider, request):
        provider._metadata = replace(
            provider.model_metadata,
            effective_context_limit_tokens=100,
            maximum_output_tokens=30,
            tokenizer_id="test-exact-counter",
        )
        return self.budget.BudgetAssessment(
            status=self.budget.BudgetStatus.WITHIN_BUDGET,
            provider=provider.provider_id,
            model_id=provider.model_id,
            budget_scope=request.budget_scope or "unspecified",
            input_tokens=60,
            output_reserve_tokens=20,
            safety_margin_tokens=10,
            effective_context_limit_tokens=100,
        )

    async def test_chat_request_preserves_messages_schema_and_enforced_limits(self) -> None:
        captured = []

        async def handler(request: httpx.Request) -> httpx.Response:
            captured.append((request.url.path, await request.aread()))
            return httpx.Response(
                200,
                json={
                    "model": "llama3.2:3b",
                    "done": True,
                    "message": {"role": "assistant", "content": '{"answer":"ok"}'},
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = self.provider_module.OllamaModelProvider(
            base_url="http://ollama.test:11434/",
            model="llama3.2:3b",
            client=client,
        )

        assessment = self._verified_assessment(provider, self.request)
        with patch.object(
            provider._budget_service, "require_verified_fit", return_value=assessment
        ) as gate:
            response = await provider.generate(self.request)

        self.assertEqual(response.content, '{"answer":"ok"}')
        self.assertEqual(provider.provider_id, "ollama")
        self.assertEqual(provider.model_id, "llama3.2:3b")
        gate.assert_called_once_with(provider.model_metadata, self.request)
        path, raw_body = captured[0]
        self.assertEqual(path, "/api/chat")
        import json

        payload = json.loads(raw_body)
        self.assertEqual(payload["model"], "llama3.2:3b")
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["options"], {"num_ctx": 100, "num_predict": 20})
        self.assertEqual(
            payload["messages"],
            [
                {"role": "system", "content": "System instructions"},
                {"role": "user", "content": self.request.input_text},
            ],
        )
        self.assertEqual(payload["format"], self.schema)
        await client.aclose()

    async def test_unverified_default_budget_blocks_before_http(self) -> None:
        calls = []

        async def handler(_request: httpx.Request) -> httpx.Response:
            calls.append(True)
            return httpx.Response(200, json={"message": {"content": "unexpected"}})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = self.provider_module.OllamaModelProvider(
            base_url="http://ollama.test:11434",
            model="llama3.2:3b",
            client=client,
        )

        with self.assertRaises(self.errors.ModelBudgetUnverifiedError):
            await provider.generate(self.request)

        self.assertEqual(calls, [])
        await client.aclose()

    async def test_http_provider_failures_are_sanitized(self) -> None:
        for status, exception_type in (
            (400, self.errors.ModelRequestRejectedError),
            (408, self.errors.ModelTimeoutError),
            (429, self.errors.ModelProviderUnavailableError),
            (503, self.errors.ModelProviderUnavailableError),
        ):
            async def handler(_request: httpx.Request, status_code=status) -> httpx.Response:
                return httpx.Response(status_code, text="private local error detail")

            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            provider = self.provider_module.OllamaModelProvider(
                base_url="http://ollama.test:11434",
                model="llama3.2:3b",
                client=client,
            )
            assessment = self._verified_assessment(provider, self.request)
            with self.subTest(status=status), self.assertRaises(exception_type) as raised:
                with patch.object(
                    provider._budget_service,
                    "require_verified_fit",
                    return_value=assessment,
                ):
                    await provider.generate(self.request)
            self.assertNotIn("private local error", str(raised.exception))
            await client.aclose()

    async def test_timeouts_and_connection_errors_are_mapped(self) -> None:
        for error, expected in (
            (httpx.ReadTimeout("internal detail"), self.errors.ModelTimeoutError),
            (httpx.ConnectError("internal detail"), self.errors.ModelProviderUnavailableError),
        ):
            async def handler(_request: httpx.Request, raised=error) -> httpx.Response:
                raise raised

            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            provider = self.provider_module.OllamaModelProvider(
                base_url="http://ollama.test:11434", model="llama3.2:3b", client=client
            )
            assessment = self._verified_assessment(provider, self.request)
            with self.subTest(error=type(error).__name__), self.assertRaises(expected) as raised:
                with patch.object(
                    provider._budget_service,
                    "require_verified_fit",
                    return_value=assessment,
                ):
                    await provider.generate(self.request)
            self.assertNotIn("internal detail", str(raised.exception))
            await client.aclose()

    async def test_malformed_or_wrong_model_response_is_rejected(self) -> None:
        bodies = (
            {"model": "other-model", "done": True, "message": {"content": "{}"}},
            {"model": "llama3.2:3b", "done": False, "message": {"content": "{}"}},
            {"model": "llama3.2:3b", "done": True, "message": {"content": "  "}},
            {"model": "llama3.2:3b", "done": True, "message": {}},
        )
        for body in bodies:
            async def handler(_request: httpx.Request, response_body=body) -> httpx.Response:
                return httpx.Response(200, json=response_body)

            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            provider = self.provider_module.OllamaModelProvider(
                base_url="http://ollama.test:11434", model="llama3.2:3b", client=client
            )
            assessment = self._verified_assessment(provider, self.request)
            with self.subTest(body=body), self.assertRaises(
                self.errors.MalformedModelOutputError
            ):
                with patch.object(
                    provider._budget_service,
                    "require_verified_fit",
                    return_value=assessment,
                ):
                    await provider.generate(self.request)
            await client.aclose()

    async def test_malformed_assessment_blocks_before_http(self) -> None:
        calls = []

        async def handler(_request: httpx.Request) -> httpx.Response:
            calls.append(True)
            return httpx.Response(
                200,
                json={"model": "llama3.2:3b", "done": True, "message": {"content": "{}"}},
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = self.provider_module.OllamaModelProvider(
            base_url="http://ollama.test:11434", model="llama3.2:3b", client=client
        )
        assessment = replace(
            self._verified_assessment(provider, self.request),
            effective_context_limit_tokens=999,
        )
        with self.assertRaises(self.errors.ModelBudgetUnverifiedError):
            with patch.object(
                provider._budget_service,
                "require_verified_fit",
                return_value=assessment,
            ):
                await provider.generate(self.request)
        self.assertEqual(calls, [])
        await client.aclose()

    def test_registry_matches_exact_provider_and_model(self) -> None:
        self.assertIs(
            self.registry.resolve_model("ollama", "llama3.2:3b"), self.metadata
        )
        with self.assertRaises(self.registry.UnsupportedModelConfiguration):
            self.registry.resolve_model("ollama", "llama3.2")
        with self.assertRaises(self.registry.UnsupportedModelConfiguration):
            self.registry.resolve_model("openai", "llama3.2:3b")

        self.assertEqual(self.metadata.published_context_limit_tokens, 131072)
        self.assertIsNone(self.metadata.effective_context_limit_tokens)
        self.assertIsNone(self.metadata.tokenizer_id)
        self.assertIsNone(self.metadata.maximum_output_tokens)

    def test_factory_is_ollama_only_and_rejects_unregistered_model(self) -> None:
        settings = self.settings_module.AISettings(
            ai_model_provider="ollama", ai_model="llama3.2:3b"
        )
        provider = self.factory.create_model_provider(settings)
        self.assertEqual(provider.provider_id, "ollama")
        self.assertEqual(provider.model_id, "llama3.2:3b")
        with self.assertRaises(TypeError):
            self.factory.create_model_provider(settings, token_budget_service=object())
        with self.assertRaises(TypeError):
            self.provider_module.OllamaModelProvider(
                base_url="http://ollama.test:11434",
                model="llama3.2:3b",
                token_budget_service=object(),
            )

        unsupported_model = settings.model_copy(update={"ai_model": "qwen2.5-coder:7b"})
        with self.assertRaises(self.errors.ProviderNotConfiguredError):
            self.factory.create_model_provider(unsupported_model)

        with self.assertRaises(ValidationError):
            self.settings_module.AISettings(ai_model_provider="openai")

    def test_budget_is_per_agent_exact_and_boundary_checked(self) -> None:
        metadata = self.registry.ModelMetadata(
            provider="ollama",
            model_id="test-model",
            published_context_limit_tokens=100,
            effective_context_limit_tokens=100,
            maximum_output_tokens=30,
            tokenizer_id="test-exact-counter",
            metadata_source="unit-test fixture",
        )
        policies = {
            scope: self.budget.AgentBudgetPolicy(
                output_reserve_tokens=20,
                safety_margin_tokens=10,
            )
            for scope in ("summary", "task", "decision", "follow_up", "insight")
        }
        request_70 = self.request.model_copy(
            update={"budget_scope": "summary", "input_text": "exact-fit"}
        )
        request_71 = self.request.model_copy(
            update={"budget_scope": "task", "input_text": "over-limit"}
        )
        counter = FakeCounter({"exact-fit": (70, True), "over-limit": (71, True)})
        service = self.budget.TokenBudgetService(counter=counter, policies=policies)

        exact_fit = service.assess(metadata, request_70)
        over_limit = service.assess(metadata, request_71)

        self.assertEqual(exact_fit.status, self.budget.BudgetStatus.WITHIN_BUDGET)
        self.assertEqual(exact_fit.budget_scope, "summary")
        self.assertEqual(over_limit.status, self.budget.BudgetStatus.EXCEEDS_BUDGET)
        self.assertEqual(over_limit.budget_scope, "task")
        self.assertEqual(len(counter.requests), 2)

    def test_approximate_count_and_unconfigured_scope_never_report_fit(self) -> None:
        metadata = self.registry.ModelMetadata(
            provider="ollama",
            model_id="test-model",
            published_context_limit_tokens=100,
            effective_context_limit_tokens=100,
            maximum_output_tokens=30,
            tokenizer_id="test-counter",
            metadata_source="unit-test fixture",
        )
        policy = self.budget.AgentBudgetPolicy(20, 10)
        counter = FakeCounter({"estimated": (5, False), "unknown": (5, True)})
        service = self.budget.TokenBudgetService(
            counter=counter,
            policies={"summary": policy},
        )

        estimated = service.assess(
            metadata,
            self.request.model_copy(
                update={"budget_scope": "summary", "input_text": "estimated"}
            ),
        )
        unknown_scope = service.assess(
            metadata,
            self.request.model_copy(
                update={"budget_scope": "insight", "input_text": "unknown"}
            ),
        )

        self.assertEqual(estimated.status, self.budget.BudgetStatus.UNVERIFIED)
        self.assertEqual(unknown_scope.status, self.budget.BudgetStatus.UNVERIFIED)
        self.assertNotEqual(estimated.status, self.budget.BudgetStatus.WITHIN_BUDGET)
        self.assertIn("token_count_is_not_exact", estimated.reasons)
        self.assertIn("agent_budget_policy_unconfigured", unknown_scope.reasons)

    def test_missing_published_context_ceiling_never_reports_fit(self) -> None:
        metadata = self.registry.ModelMetadata(
            provider="ollama",
            model_id="test-model",
            published_context_limit_tokens=None,
            effective_context_limit_tokens=100,
            maximum_output_tokens=30,
            tokenizer_id="test-counter",
            metadata_source="unit-test fixture",
        )
        service = self.budget.TokenBudgetService(
            counter=FakeCounter({"full": (5, True)}),
            policies={"summary": self.budget.AgentBudgetPolicy(20, 10)},
        )
        assessment = service.assess(
            metadata,
            self.request.model_copy(
                update={"budget_scope": "summary", "input_text": "full"}
            ),
        )
        self.assertEqual(assessment.status, self.budget.BudgetStatus.UNVERIFIED)
        self.assertIn("published_model_context_unverified", assessment.reasons)

    def test_counter_errors_or_invalid_results_never_report_fit(self) -> None:
        metadata = self.registry.ModelMetadata(
            provider="ollama",
            model_id="test-model",
            published_context_limit_tokens=100,
            effective_context_limit_tokens=100,
            maximum_output_tokens=30,
            tokenizer_id="test-counter",
            metadata_source="unit-test fixture",
        )
        policy = self.budget.AgentBudgetPolicy(20, 10)

        class BrokenCounter:
            def count_request_tokens(self, _metadata, _request):
                raise RuntimeError("counter internals")

        class InvalidCounter:
            def __init__(self):
                self.token_count = importlib.import_module(
                    "llm.token_budget"
                ).TokenCount

            def count_request_tokens(self, _metadata, _request):
                return self.token_count(value=5.5, exact=True)

        for counter, reason in (
            (BrokenCounter(), "token_counter_failed"),
            (InvalidCounter(), "token_counter_returned_invalid_result"),
        ):
            with self.subTest(reason=reason):
                assessment = self.budget.TokenBudgetService(
                    counter=counter, policies={"summary": policy}
                ).assess(
                    metadata,
                    self.request.model_copy(update={"budget_scope": "summary"}),
                )
                self.assertEqual(assessment.status, self.budget.BudgetStatus.UNVERIFIED)
                self.assertIn(reason, assessment.reasons)
                self.assertNotEqual(
                    assessment.status, self.budget.BudgetStatus.WITHIN_BUDGET
                )

    def test_budget_failures_map_to_safe_processing_errors(self) -> None:
        processing_results = importlib.import_module("app.processing_results")
        for error, code in (
            (
                self.errors.ModelBudgetUnverifiedError(),
                processing_results.ProcessingErrorCode.TOKEN_BUDGET_UNVERIFIED,
            ),
            (
                self.errors.ModelBudgetExceededError(),
                processing_results.ProcessingErrorCode.TOKEN_BUDGET_EXCEEDED,
            ),
        ):
            with self.subTest(code=code):
                failure = processing_results.failure_for_exception(error)
                self.assertEqual(failure.code, code)
                self.assertEqual(failure.message, error.safe_message)

    async def test_all_five_agents_assign_their_budget_scope(self) -> None:
        _prepare_ai_imports()
        from agents.decision_agent import DecisionAgent
        from agents.followup_agent import FollowUpAgent
        from agents.insight_agent import InsightAgent
        from agents.summary_agent import SummaryAgent
        from agents.task_agent import TaskAgent
        from app.contracts import AgentInput, TranscriptContent
        from shared.schemas.transcript import TranscriptSegment

        agent_input = AgentInput(
            meeting_id="b969d5d3-caa0-4dae-bb44-f9275ce70cdd",
            transcript=TranscriptContent(
                transcript_id="8679360a-ec79-44de-a3d0-bf168c48288a",
                segments=[TranscriptSegment(index=0, text="A short test transcript.")],
            ),
        )
        cases = (
            (SummaryAgent, "summary"),
            (TaskAgent, "task"),
            (DecisionAgent, "decision"),
            (FollowUpAgent, "follow_up"),
            (InsightAgent, "insight"),
        )

        for agent_class, expected_scope in cases:
            with self.subTest(agent=agent_class.__name__):
                generated = AsyncMock(return_value=None)
                with patch("agents.base.generate_structured_output", generated):
                    await agent_class(object()).execute(agent_input)
                self.assertEqual(generated.await_args.kwargs["budget_scope"], expected_scope)


if __name__ == "__main__":
    unittest.main()
