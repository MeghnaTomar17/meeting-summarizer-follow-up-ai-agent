"""Credential-free tests for the OpenAI ModelProvider adapter."""

from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import openai
from pydantic import BaseModel, SecretStr, ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
AI_SERVICE_ROOT = BACKEND_ROOT / "ai-service"
SERVICE_NAMES = (
    "gateway-service",
    "meeting-service",
    "ai-service",
    "search-service",
    "worker-service",
)
_NO_RESPONSE = object()


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


class FakeCompletions:
    def __init__(
        self, *, content="{\"value\":\"ok\"}", response=_NO_RESPONSE, error=None
    ):
        self.content = content
        self.response = response
        self.error = error
        self.calls: list[dict] = []

    async def create(self, **parameters):
        self.calls.append(parameters)
        if self.error is not None:
            raise self.error
        if self.response is not _NO_RESPONSE:
            return self.response
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


class FakeOpenAIClient:
    def __init__(self, completions: FakeCompletions):
        self.chat = SimpleNamespace(completions=completions)
        self.close = AsyncMock()


class ProviderOutput(BaseModel):
    value: str


class OpenAIProviderTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _prepare_ai_imports()
        self.contracts = importlib.import_module("app.contracts")
        self.errors = importlib.import_module("llm.errors")
        self.provider_module = importlib.import_module("llm.openai_client")
        self.settings_module = importlib.import_module("app.config.settings")
        self.provider_type = self.provider_module.OpenAIModelProvider
        self.request = self.contracts.ModelRequest(
            instructions="Follow the task instructions.",
            input_text="Transcript source text.",
            response_schema=ProviderOutput.model_json_schema(),
        )

    def _provider(self, completions: FakeCompletions, **overrides):
        options = {
            "api_key": SecretStr("unit-test-only-secret"),
            "model": "configured-test-model",
            "client": FakeOpenAIClient(completions),
        }
        options.update(overrides)
        return self.provider_type(**options)

    async def test_provider_maps_request_schema_and_neutral_response(self) -> None:
        completions = FakeCompletions(content='{"value":"validated later"}')
        provider = self._provider(completions)

        response = await provider.generate(self.request)

        self.assertIsInstance(provider, importlib.import_module("llm.provider").ModelProvider)
        self.assertIsInstance(response, self.contracts.ModelResponse)
        self.assertEqual(response.model_dump(), {"content": '{"value":"validated later"}'})
        self.assertEqual(
            completions.calls[0]["messages"],
            [
                {"role": "system", "content": self.request.instructions},
                {"role": "user", "content": self.request.input_text},
            ],
        )
        self.assertEqual(completions.calls[0]["model"], "configured-test-model")
        response_format = completions.calls[0]["response_format"]
        self.assertEqual(response_format["type"], "json_schema")
        self.assertEqual(response_format["json_schema"]["name"], "ProviderOutput")
        self.assertEqual(response_format["json_schema"]["schema"], self.request.response_schema)
        self.assertFalse(response_format["json_schema"]["strict"])
        self.assertNotIn("unit-test-only-secret", self.request.model_dump_json())

    async def test_settings_supply_model_credential_and_timeout_without_requesting_network(
        self,
    ) -> None:
        settings = self.settings_module.AISettings(
            _env_file=None,
            openai_api_key=SecretStr("unit-test-only-secret"),
            openai_model="settings-selected-model",
            openai_timeout_seconds=4.25,
        )
        fake_client = FakeOpenAIClient(FakeCompletions())
        provider = self.provider_type.from_settings(settings)

        with patch.object(
            self.provider_module, "AsyncOpenAI", return_value=fake_client
        ) as sdk_factory:
            response = await provider.generate(self.request)
            sdk_factory.assert_called_once_with(
                api_key="unit-test-only-secret",
                timeout=4.25,
                max_retries=0,
            )

        self.assertEqual(
            fake_client.chat.completions.calls[0]["model"],
            "settings-selected-model",
        )
        self.assertEqual(response.content, '{"value":"ok"}')
        await provider.aclose()
        fake_client.close.assert_awaited_once()

    async def test_missing_credentials_or_model_fail_safely_before_sdk_creation(
        self,
    ) -> None:
        for options in (
            {"api_key": None, "model": "configured-test-model"},
            {"api_key": SecretStr("unit-test-only-secret"), "model": None},
            {"api_key": SecretStr("  "), "model": "configured-test-model"},
        ):
            with self.subTest(options=options), patch.object(
                self.provider_module, "AsyncOpenAI"
            ) as sdk_factory:
                provider = self.provider_type(**options)
                with self.assertRaises(self.errors.ProviderNotConfiguredError) as raised:
                    await provider.generate(self.request)
                self.assertEqual(str(raised.exception), "No model provider is configured.")
                self.assertNotIn("unit-test-only-secret", str(raised.exception))
                sdk_factory.assert_not_called()

    def test_production_provider_factory_rejects_missing_required_configuration(self):
        settings = self.settings_module.AISettings(
            _env_file=None,
            app_env="production",
            openai_api_key=None,
            openai_model=None,
        )

        with self.assertRaises(self.errors.ProviderNotConfiguredError):
            self.provider_type.from_settings(settings)

    async def test_authentication_failure_maps_to_sanitized_request_rejection(self):
        secret = "auth-response-secret"
        request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        response = httpx.Response(401, request=request)
        error = openai.AuthenticationError(
            f"Authorization: Bearer {secret}",
            response=response,
            body={"message": secret},
        )
        provider = self._provider(FakeCompletions(error=error))

        with self.assertRaises(self.errors.ModelRequestRejectedError) as raised:
            await provider.generate(self.request)

        self.assertNotIn(secret, str(raised.exception))
        self.assertNotIn("Bearer", str(raised.exception))

    async def test_rate_limit_and_server_errors_map_to_provider_unavailable(self):
        request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        for error in (
            openai.RateLimitError(
                "private rate detail",
                response=httpx.Response(429, request=request),
                body={"message": "private rate detail"},
            ),
            openai.InternalServerError(
                "private server detail",
                response=httpx.Response(503, request=request),
                body={"message": "private server detail"},
            ),
        ):
            with self.subTest(error=type(error).__name__):
                provider = self._provider(FakeCompletions(error=error))
                with self.assertRaises(self.errors.ModelProviderUnavailableError) as raised:
                    await provider.generate(self.request)
                self.assertNotIn("private", str(raised.exception))

    async def test_timeout_and_connection_errors_use_controlled_categories(self):
        request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        cases = (
            (openai.APITimeoutError(request=request), self.errors.ModelTimeoutError),
            (
                openai.APIConnectionError(
                    message="Authorization: Bearer connection-secret", request=request
                ),
                self.errors.ModelProviderUnavailableError,
            ),
        )
        for error, expected in cases:
            with self.subTest(error=type(error).__name__):
                provider = self._provider(FakeCompletions(error=error))
                with self.assertRaises(expected) as raised:
                    await provider.generate(self.request)
                self.assertNotIn("connection-secret", str(raised.exception))
                self.assertNotIn("Authorization", str(raised.exception))

    async def test_unexpected_sdk_error_is_sanitized(self):
        provider = self._provider(
            FakeCompletions(error=RuntimeError("sdk body exposed secret-value"))
        )

        with self.assertRaises(self.errors.UnexpectedModelProviderError) as raised:
            await provider.generate(self.request)

        self.assertNotIn("secret-value", str(raised.exception))

    async def test_malformed_or_empty_provider_responses_are_controlled(self):
        malformed_responses = (
            None,
            SimpleNamespace(choices=[]),
            SimpleNamespace(choices=[SimpleNamespace(message=None)]),
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None))]),
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="  "))]),
        )
        for response in malformed_responses:
            with self.subTest(response=response):
                provider = self._provider(FakeCompletions(response=response))
                with self.assertRaises(self.errors.MalformedModelOutputError):
                    await provider.generate(self.request)

    async def test_response_without_schema_omits_provider_specific_json_mode(self):
        completions = FakeCompletions(content="plain text response")
        provider = self._provider(completions)
        request = self.contracts.ModelRequest(
            instructions="Answer briefly.", input_text="What was discussed?"
        )

        response = await provider.generate(request)

        self.assertEqual(response.content, "plain text response")
        self.assertNotIn("response_format", completions.calls[0])

    async def test_output_flows_through_shared_structured_validation(self):
        completions = FakeCompletions(content='{"value":"typed result"}')
        provider = self._provider(completions)
        structured_output = importlib.import_module("llm.structured_output")
        request = self.contracts.ModelRequest(
            instructions="Return JSON.", input_text="Source text."
        )

        result = await structured_output.generate_structured_output(
            provider, request, ProviderOutput
        )

        self.assertIsInstance(result, ProviderOutput)
        self.assertEqual(result.value, "typed result")
        self.assertEqual(
            completions.calls[0]["response_format"]["json_schema"]["schema"],
            ProviderOutput.model_json_schema(),
        )

    def test_timeout_setting_must_be_positive(self):
        with self.assertRaises(ValidationError):
            self.settings_module.AISettings(
                _env_file=None,
                openai_api_key=None,
                openai_model="test-model",
                openai_timeout_seconds=0,
            )


if __name__ == "__main__":
    unittest.main()
