"""Phase 10.2 embedding boundary tests using deterministic in-memory providers."""

from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

from pydantic import SecretStr, ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SEARCH_ROOT = BACKEND_ROOT / "search-service"
MEETING_ID = UUID("d146f98d-d557-4b89-a746-3e48e73d46b1")
TRANSCRIPT_ID = UUID("084c3a14-1a7f-41c9-a7c8-1e195aa5313a")
OWNER_ID = UUID("10000000-0000-0000-0000-000000000001")
ORG_ID = UUID("20000000-0000-0000-0000-000000000002")


def _prepare_search_imports() -> None:
    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            del sys.modules[module_name]
        elif module_name.split(".", 1)[0] in {"chunking", "embeddings", "vectorstore"}:
            del sys.modules[module_name]
    for service in ("gateway-service", "meeting-service", "ai-service", "search-service"):
        root = str(BACKEND_ROOT / service)
        while root in sys.path:
            sys.path.remove(root)
    sys.path[:0] = [str(SEARCH_ROOT), str(BACKEND_ROOT)]


class FakeEmbeddings:
    def __init__(self, *, response=None, error=None):
        self.response = response
        self.error = error
        self.calls: list[dict] = []

    async def create(self, **parameters):
        self.calls.append(parameters)
        if self.error is not None:
            raise self.error
        return self.response or SimpleNamespace(
            data=[
                SimpleNamespace(index=1, embedding=[0.4, 0.5, 0.6]),
                SimpleNamespace(index=0, embedding=[0.1, 0.2, 0.3]),
            ]
        )


class FakeOpenAIClient:
    def __init__(self, embeddings: FakeEmbeddings):
        self.embeddings = embeddings
        self.close = AsyncMock()


class DeterministicProvider:
    def __init__(self, identity):
        self.identity = identity
        self.requests = []
        self.aclose = AsyncMock()

    async def embed(self, request):
        self.requests.append(request)
        return importlib.import_module("embeddings.contracts").EmbeddingResponse(
            model_identity=self.identity,
            vectors=[[float(index), 0.2, 0.3] for index, _ in enumerate(request.texts)],
        )


class SearchEmbeddingProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _prepare_search_imports()
        self.httpx = importlib.import_module("httpx")
        self.openai = importlib.import_module("openai")
        self.contracts = importlib.import_module("embeddings.contracts")
        self.errors = importlib.import_module("embeddings.errors")
        self.provider_module = importlib.import_module("embeddings.openai_provider")
        self.factory = importlib.import_module("embeddings.factory")
        self.service_module = importlib.import_module("embeddings.service")
        self.settings_module = importlib.import_module("app.config.settings")
        self.identity = self.contracts.EmbeddingModelIdentity(
            provider="openai", model="text-embedding-3-small", dimensions=3
        )
        self.request = self.contracts.EmbeddingRequest(
            model_identity=self.identity,
            texts=["First transcript chunk", "Second transcript chunk"],
        )

    def _provider(self, embeddings: FakeEmbeddings, **overrides):
        options = {
            "api_key": SecretStr("phase10-test-secret"),
            "model": self.identity.model,
            "dimensions": self.identity.dimensions,
            "client": FakeOpenAIClient(embeddings),
        }
        options.update(overrides)
        return self.provider_module.OpenAIEmbeddingProvider(**options)

    async def test_openai_adapter_returns_ordered_typed_vectors_and_metadata(self):
        embeddings = FakeEmbeddings()
        provider = self._provider(embeddings)

        response = await provider.embed(self.request)

        self.assertIsInstance(response, self.contracts.EmbeddingResponse)
        self.assertEqual(response.model_identity, self.identity)
        self.assertEqual(response.vectors, [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
        self.assertEqual(
            embeddings.calls,
            [{"model": self.identity.model, "input": self.request.texts, "dimensions": 3}],
        )

    async def test_factory_and_service_embed_existing_chunks_through_provider_port(self):
        settings = self.settings_module.SearchSettings(
            _env_file=None,
            embedding_api_key=SecretStr("phase10-test-secret"),
            embedding_dimensions=3,
        )
        embeddings = FakeEmbeddings()
        provider = self.factory.create_embedding_provider(
            settings, client=FakeOpenAIClient(embeddings)
        )
        service = self.service_module.EmbeddingService(provider, self.identity)
        chunks = [
            importlib.import_module("chunking.contracts").TranscriptChunk(
                chunk_id=UUID(int=1), meeting_id=MEETING_ID, transcript_id=TRANSCRIPT_ID,
                owner_id=OWNER_ID, organization_id=ORG_ID, chunk_index=0,
                source_segments=[{"index": 0}], text="First transcript chunk",
            ),
            importlib.import_module("chunking.contracts").TranscriptChunk(
                chunk_id=UUID(int=2), meeting_id=MEETING_ID, transcript_id=TRANSCRIPT_ID,
                owner_id=OWNER_ID, organization_id=ORG_ID, chunk_index=1,
                source_segments=[{"index": 1}], text="Second transcript chunk",
            ),
        ]

        response = await service.embed_chunks(chunks)

        self.assertEqual(response.model_identity, self.identity)
        self.assertEqual(len(response.vectors), 2)
        self.assertEqual(embeddings.calls[0]["input"], [chunk.text for chunk in chunks])

    async def test_invalid_or_mismatched_inputs_do_not_call_provider(self):
        with self.assertRaises(ValidationError):
            self.contracts.EmbeddingRequest(model_identity=self.identity, texts=[])
        with self.assertRaises(ValidationError):
            self.contracts.EmbeddingRequest(model_identity=self.identity, texts=[" "])
        embeddings = FakeEmbeddings()
        provider = self._provider(embeddings)
        different_model = self.contracts.EmbeddingRequest(
            model_identity=self.contracts.EmbeddingModelIdentity(
                provider="openai", model="other-model", dimensions=3
            ),
            texts=["text"],
        )
        with self.assertRaises(self.errors.EmbeddingRequestRejectedError):
            await provider.embed(different_model)
        self.assertEqual(embeddings.calls, [])
        with self.assertRaises(ValidationError):
            await self.service_module.EmbeddingService(
                provider, self.identity
            ).embed_texts([])

    async def test_malformed_vectors_and_unexpected_responses_are_controlled(self):
        malformed = (
            SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[0.1, 0.2])]),
            SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[0.1, float("inf"), 0.3]),
                                  SimpleNamespace(index=1, embedding=[0.1, 0.2, 0.3])]),
            SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[0.1, 0.2, 0.3])]),
            SimpleNamespace(data=[SimpleNamespace(index=1, embedding=[0.1, 0.2, 0.3]),
                                  SimpleNamespace(index=1, embedding=[0.4, 0.5, 0.6])]),
        )
        for response in malformed:
            with self.subTest(response=response):
                provider = self._provider(FakeEmbeddings(response=response))
                with self.assertRaises(self.errors.MalformedEmbeddingResponseError):
                    await provider.embed(self.request)

    async def test_provider_failures_are_sanitized(self):
        request = self.httpx.Request("POST", "https://api.openai.com/v1/embeddings")
        cases = (
            (self.openai.APITimeoutError(request=request), self.errors.EmbeddingTimeoutError),
            (self.openai.APIConnectionError(message="secret credential", request=request),
             self.errors.EmbeddingProviderUnavailableError),
            (self.openai.AuthenticationError(
                "Bearer leaked-secret", response=self.httpx.Response(401, request=request),
                body={"message": "leaked-secret"},
            ), self.errors.EmbeddingRequestRejectedError),
            (self.openai.RateLimitError(
                "private detail", response=self.httpx.Response(429, request=request), body={}
            ), self.errors.EmbeddingProviderUnavailableError),
            (RuntimeError("SDK exposed leaked-secret"), self.errors.UnexpectedEmbeddingProviderError),
        )
        for error, expected in cases:
            with self.subTest(error=type(error).__name__):
                provider = self._provider(FakeEmbeddings(error=error))
                with self.assertRaises(expected) as raised:
                    await provider.embed(self.request)
                self.assertNotIn("leaked-secret", str(raised.exception))
                self.assertNotIn("credential", str(raised.exception))

    async def test_configuration_validates_endpoint_and_factory_provider(self):
        with self.assertRaises(ValidationError):
            self.settings_module.SearchSettings(_env_file=None, embedding_base_url="file:///bad")
        with self.assertRaises(ValidationError):
            self.settings_module.SearchSettings(
                _env_file=None, embedding_base_url="https://user:secret@example.test"
            )
        with self.assertRaises(ValidationError):
            self.settings_module.SearchSettings(
                _env_file=None, embedding_base_url="https://example.test/?token=secret"
            )
        normalized_provider = self.settings_module.SearchSettings(
            _env_file=None, embedding_provider=" OpenAI "
        )
        self.assertEqual(normalized_provider.embedding_provider, "openai")
        settings = self.settings_module.SearchSettings(
            _env_file=None, embedding_provider="unsupported"
        )
        with self.assertRaises(self.errors.EmbeddingProviderNotConfiguredError):
            self.factory.create_embedding_provider(settings)

    async def test_credentials_stay_in_settings_and_sdk_construction_is_configured(self):
        settings = self.settings_module.SearchSettings(
            _env_file=None,
            embedding_api_key=SecretStr("do-not-leak-this"),
            embedding_base_url="https://embeddings.example.test/v1/",
            embedding_timeout_seconds=4.5,
            embedding_dimensions=3,
        )
        provider = self.provider_module.OpenAIEmbeddingProvider.from_settings(settings)
        fake_client = FakeOpenAIClient(FakeEmbeddings())
        with patch.object(self.provider_module, "AsyncOpenAI", return_value=fake_client) as sdk:
            await provider.embed(self.request)
        sdk.assert_called_once_with(
            api_key="do-not-leak-this",
            timeout=4.5,
            max_retries=0,
            base_url="https://embeddings.example.test/v1",
        )
        self.assertNotIn("do-not-leak-this", repr(settings))
        self.assertNotIn("do-not-leak-this", self.request.model_dump_json())
        self.assertNotIn("do-not-leak-this", repr(provider))

    async def test_missing_api_key_fails_before_network_or_sdk_creation(self):
        settings = self.settings_module.SearchSettings(_env_file=None, embedding_dimensions=3)
        provider = self.provider_module.OpenAIEmbeddingProvider.from_settings(settings)
        with patch.object(self.provider_module, "AsyncOpenAI") as sdk:
            with self.assertRaises(self.errors.EmbeddingProviderNotConfiguredError) as raised:
                await provider.embed(self.request)
        sdk.assert_not_called()
        self.assertNotIn("secret", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
