"""Provider abstraction and structured-output boundary tests."""

from __future__ import annotations

import importlib
import typing
import sys
import unittest
from pathlib import Path

from pydantic import BaseModel

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


class ValidatedSummary(BaseModel):
    title: str
    points: list[str]


class StubModelProvider:
    def __init__(self, response_content: str = "{}", error: Exception | None = None):
        self.response_content = response_content
        self.error = error
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        contracts = importlib.import_module("app.contracts")
        return contracts.ModelResponse(content=self.response_content)


class ModelAbstractionTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _prepare_ai_imports()
        self.contracts = importlib.import_module("app.contracts")
        self.errors = importlib.import_module("llm.errors")
        self.provider_module = importlib.import_module("llm.provider")
        self.orchestrator_module = importlib.import_module("agents.orchestrator")
        self.request = self.contracts.ModelRequest(
            instructions="Return the requested JSON structure.",
            input_text="Discussed release readiness.",
        )

    async def test_mock_provider_satisfies_protocol_and_is_injected(self) -> None:
        provider = StubModelProvider(
            '{"title":"Release readiness","points":["Confirm deployment"]}'
        )
        self.assertIsInstance(provider, self.provider_module.ModelProvider)

        orchestrator = self.orchestrator_module.AIProcessingOrchestrator(
            model_provider=provider
        )
        result = await orchestrator.generate_structured(self.request, ValidatedSummary)

        self.assertIsInstance(result, ValidatedSummary)
        self.assertEqual(result.points, ["Confirm deployment"])
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(
            provider.requests[0].response_schema,
            ValidatedSummary.model_json_schema(),
        )
        self.assertEqual(provider.requests[0].input_text, self.request.input_text)

    def test_orchestrator_dependency_is_the_provider_protocol(self) -> None:
        annotation = typing.get_type_hints(
            self.orchestrator_module.AIProcessingOrchestrator.__init__
        )["model_provider"]

        self.assertEqual(annotation, self.provider_module.ModelProvider | None)

    async def test_model_request_does_not_mutate_shared_input_contract(self) -> None:
        provider = StubModelProvider('{"title":"Ready","points":[]}')
        orchestrator = self.orchestrator_module.AIProcessingOrchestrator(provider)

        await orchestrator.generate_structured(self.request, ValidatedSummary)

        self.assertIsNone(self.request.response_schema)
        self.assertIsNotNone(provider.requests[0].response_schema)

    async def test_malformed_json_or_wrong_shape_is_a_controlled_failure(self) -> None:
        malformed_payload = '{"title":"x","points":"secret-token-value"}'
        provider = StubModelProvider(malformed_payload)
        orchestrator = self.orchestrator_module.AIProcessingOrchestrator(provider)

        with self.assertRaises(self.errors.MalformedModelOutputError) as raised:
            await orchestrator.generate_structured(self.request, ValidatedSummary)

        self.assertNotIn("secret-token-value", str(raised.exception))
        self.assertNotIn(malformed_payload, str(raised.exception))

    async def test_malformed_provider_response_object_is_a_controlled_failure(self) -> None:
        class InvalidResponseProvider:
            async def generate(self, _request):
                return {"private": "provider-response"}

        orchestrator = self.orchestrator_module.AIProcessingOrchestrator(
            InvalidResponseProvider()
        )

        with self.assertRaises(self.errors.MalformedModelOutputError) as raised:
            await orchestrator.generate_structured(self.request, ValidatedSummary)

        self.assertNotIn("provider-response", str(raised.exception))

    async def test_missing_provider_is_deterministic(self) -> None:
        orchestrator = self.orchestrator_module.AIProcessingOrchestrator()

        with self.assertRaises(self.errors.ProviderNotConfiguredError) as raised:
            await orchestrator.generate_structured(self.request, ValidatedSummary)

        self.assertEqual(str(raised.exception), "No model provider is configured.")

    async def test_expected_provider_failures_remain_sanitized(self) -> None:
        expected = (
            self.errors.ModelProviderUnavailableError,
            self.errors.ModelRequestRejectedError,
        )
        for error_type in expected:
            with self.subTest(error_type=error_type.__name__):
                provider = StubModelProvider(error=error_type())
                orchestrator = self.orchestrator_module.AIProcessingOrchestrator(provider)
                with self.assertRaises(error_type) as raised:
                    await orchestrator.generate_structured(
                        self.request, ValidatedSummary
                    )
                self.assertNotIn("credential", str(raised.exception).lower())

    async def test_timeout_and_unexpected_provider_errors_are_normalized(self) -> None:
        cases = (
            (TimeoutError("api_key=private-value"), self.errors.ModelTimeoutError),
            (
                RuntimeError("provider response contained private-value"),
                self.errors.UnexpectedModelProviderError,
            ),
        )
        for error, expected_type in cases:
            with self.subTest(expected_type=expected_type.__name__):
                provider = StubModelProvider(error=error)
                orchestrator = self.orchestrator_module.AIProcessingOrchestrator(provider)
                with self.assertRaises(expected_type) as raised:
                    await orchestrator.generate_structured(
                        self.request, ValidatedSummary
                    )
                self.assertNotIn("private-value", str(raised.exception))

    async def test_provider_neutral_response_validates_through_pydantic(self) -> None:
        response = self.contracts.ModelResponse(content='{"title":"x","points":[]}')

        validated = ValidatedSummary.model_validate_json(response.content)

        self.assertEqual(validated.title, "x")


if __name__ == "__main__":
    unittest.main()
