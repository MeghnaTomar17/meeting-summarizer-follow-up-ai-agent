"""Focused Search Service transcript-indexing orchestration tests."""

from __future__ import annotations

import asyncio
import importlib
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from pydantic import SecretStr

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SEARCH_ROOT = BACKEND_ROOT / "search-service"


def _load_search():
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
        elif name.split(".", 1)[0] in {"chunking", "embeddings", "indexing", "vectorstore"}:
            del sys.modules[name]
    for service in ("gateway-service", "meeting-service", "ai-service", "search-service"):
        path = str(BACKEND_ROOT / service)
        while path in sys.path:
            sys.path.remove(path)
    sys.path[:0] = [str(SEARCH_ROOT), str(BACKEND_ROOT)]


class _Provider:
    def __init__(self, contracts, identity, *, failure=None):
        self.contracts = contracts
        self.identity = identity
        self.failure = failure
        self.requests = []

    async def embed(self, request):
        self.requests.append(request)
        if self.failure:
            raise self.failure
        return self.contracts.EmbeddingResponse(
            model_identity=self.identity,
            vectors=[[0.1, 0.2, 0.3] for _ in request.texts],
        )

    async def aclose(self):
        return None


class TranscriptIndexingServiceTests(unittest.TestCase):
    def setUp(self):
        _load_search()
        self.config = importlib.import_module("app.config.settings")
        contracts = importlib.import_module("embeddings.contracts")
        service_type = importlib.import_module("indexing.service").TranscriptIndexingService
        source_contracts = importlib.import_module("shared.schemas.transcript_indexing")
        self.meeting_id = uuid.uuid4()
        self.transcript_id = uuid.uuid4()
        self.owner_id = uuid.uuid4()
        self.organization_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        transcript = importlib.import_module("shared.schemas.transcript").TranscriptInDB(
            id=str(self.transcript_id), meeting_id=str(self.meeting_id),
            segments=[
                {"index": 0, "text": "first passage"},
                {"index": 1, "text": "second passage"},
            ], language="en", created_at=now, updated_at=now,
        )
        self.source = source_contracts.TranscriptIndexSource(
            transcript=transcript, organization_id=self.organization_id,
        )
        self.settings = self.config.SearchSettings(
            _env_file=None,
            embedding_provider="openai",
            embedding_model="unit-model",
            embedding_dimensions=3,
            transcript_chunk_max_characters=13,
            embedding_api_key=SecretStr("unused-test-value"),
        )
        self.identity = contracts.EmbeddingModelIdentity(
            provider="openai", model="unit-model", dimensions=3,
        )
        self.provider = _Provider(contracts, self.identity)
        self.embeddings = importlib.import_module("embeddings.service").EmbeddingService(
            self.provider, self.identity,
        )
        self.repository = type("Repository", (), {})()
        self.repository.initialize_collection = AsyncMock()
        self.repository.upsert_transcript_batch = AsyncMock()
        self.repository.aclose = AsyncMock()
        self.service = service_type(self.embeddings, self.repository, self.settings)

    def test_success_uses_verified_owner_and_source_organization_scope(self):
        result = asyncio.run(self.service.index(
            self.source, meeting_id=self.meeting_id, owner_id=self.owner_id,
        ))
        batch = self.repository.upsert_transcript_batch.await_args.args[0]
        self.assertEqual(result.status, "indexed")
        self.assertEqual(result.chunk_count, 2)
        self.assertEqual({record.chunk.owner_id for record in batch.records}, {self.owner_id})
        self.assertEqual({record.chunk.organization_id for record in batch.records}, {self.organization_id})
        self.assertEqual(self.repository.initialize_collection.await_count, 1)
        self.assertEqual(len(self.provider.requests), 1)

    def test_embedding_failure_happens_before_collection_or_qdrant_mutation(self):
        self.provider.failure = RuntimeError("provider credential secret")
        from retrieval.errors import SemanticSearchUnavailableError
        with self.assertRaises(SemanticSearchUnavailableError):
            asyncio.run(self.service.index(
                self.source, meeting_id=self.meeting_id, owner_id=self.owner_id,
            ))
        self.repository.initialize_collection.assert_not_awaited()
        self.repository.upsert_transcript_batch.assert_not_awaited()

    def test_qdrant_failure_is_sanitized(self):
        self.repository.upsert_transcript_batch.side_effect = RuntimeError("qdrant token")
        from retrieval.errors import SemanticSearchUnavailableError
        with self.assertRaises(SemanticSearchUnavailableError) as raised:
            asyncio.run(self.service.index(
                self.source, meeting_id=self.meeting_id, owner_id=self.owner_id,
            ))
        self.assertNotIn("token", str(raised.exception))

    def test_empty_transcript_is_explicit_and_replaces_after_source_was_found(self):
        source_type = type(self.source)
        self.source = source_type(
            transcript=self.source.transcript.model_copy(update={"segments": []}),
            organization_id=self.organization_id,
        )
        result = asyncio.run(self.service.index(
            self.source, meeting_id=self.meeting_id, owner_id=self.owner_id,
        ))
        self.assertEqual((result.status, result.chunk_count), ("empty", 0))
        self.repository.upsert_transcript_batch.assert_awaited_once()
        self.assertTrue(self.repository.upsert_transcript_batch.await_args.args[0].is_empty)
        self.assertEqual(self.provider.requests, [])

    def test_meeting_identity_mismatch_rejected_before_embedding_or_qdrant(self):
        from shared.exceptions.common import ValidationError
        with self.assertRaises(ValidationError):
            asyncio.run(self.service.index(
                self.source, meeting_id=uuid.uuid4(), owner_id=self.owner_id,
            ))
        self.assertEqual(self.provider.requests, [])
        self.repository.initialize_collection.assert_not_awaited()

    def test_search_api_derives_owner_from_verified_dependency_and_rejects_owner_body(self):
        _load_search()
        app = importlib.import_module("app.main").app
        auth = importlib.import_module("app.auth.dependencies")
        dependencies = importlib.import_module("app.dependencies")
        user_id = uuid.uuid4()
        service = type("FakeIndexingService", (), {})()
        service.index = AsyncMock(return_value=importlib.import_module(
            "shared.schemas.transcript_indexing"
        ).TranscriptIndexingResult(
            meeting_id=self.meeting_id, transcript_id=self.transcript_id,
            status="indexed", chunk_count=1,
        ))
        app.dependency_overrides[auth.get_authenticated_user_id] = lambda: user_id
        app.dependency_overrides[dependencies.get_transcript_indexing_service] = lambda: service
        client = TestClient(app, raise_server_exceptions=False)
        try:
            payload = self.source.model_dump(mode="json")
            response = client.post(
                f"/search/meetings/{self.meeting_id}/index", json=payload,
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(service.index.await_args.kwargs["owner_id"], user_id)
            self.assertEqual(service.index.await_args.kwargs["meeting_id"], self.meeting_id)
            rejected = client.post(
                f"/search/meetings/{self.meeting_id}/index",
                json={**payload, "owner_id": str(uuid.uuid4())},
            )
            self.assertEqual(rejected.status_code, 422)
            self.assertEqual(service.index.await_count, 1)
            app.dependency_overrides.pop(auth.get_authenticated_user_id)
            unauthenticated = client.post(
                f"/search/meetings/{self.meeting_id}/index", json=payload,
            )
            self.assertEqual(unauthenticated.status_code, 401)
            self.assertEqual(service.index.await_count, 1)
        finally:
            client.close()
            app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
