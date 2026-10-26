"""Indexing-to-retrieval flow tests using real Search services and repository."""

from __future__ import annotations

import importlib
import math
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import httpx
from jose import jwt

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SEARCH_ROOT = BACKEND_ROOT / "search-service"


def _load_search_app():
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
        elif name.split(".", 1)[0] in {
            "chunking", "embeddings", "indexing", "retrieval", "vectorstore"
        }:
            del sys.modules[name]
    for service in ("gateway-service", "meeting-service", "ai-service", "search-service"):
        path = str(BACKEND_ROOT / service)
        while path in sys.path:
            sys.path.remove(path)
    sys.path[:0] = [str(SEARCH_ROOT), str(BACKEND_ROOT)]
    return (
        importlib.import_module("app.main").app,
        importlib.import_module("app.config.settings"),
        importlib.import_module("app.dependencies"),
    )


class DeterministicEmbeddingProvider:
    """Small local embedding fixture with predictable semantic neighbors."""

    def __init__(self, identity):
        self.identity = identity
        self.requests = []
        self.failure = None

    async def embed(self, request):
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        vectors = []
        for text in request.texts:
            normalized = text.lower()
            if "retired" in normalized:
                vector = [0.0, 1.0, 0.0]
            elif "budget" in normalized or "project" in normalized:
                vector = [1.0, 0.0, 0.0]
            else:
                vector = [0.0, 0.0, 1.0]
            vectors.append(vector)
        contracts = importlib.import_module("embeddings.contracts")
        return contracts.EmbeddingResponse(model_identity=self.identity, vectors=vectors)

    async def aclose(self):
        return None


class InMemoryQdrantClient:
    """Qdrant client port implementing real repository calls without a server."""

    def __init__(self):
        self.collections = {}
        self.points = {}
        self.calls = []

    async def collection_exists(self, collection_name):
        self.calls.append(("collection_exists", collection_name))
        return collection_name in self.collections

    async def get_collection(self, collection_name):
        self.calls.append(("get_collection", collection_name))
        if collection_name not in self.collections:
            raise RuntimeError("collection not found")
        return self.collections[collection_name]

    async def create_collection(self, *, collection_name, vectors_config):
        self.calls.append(("create_collection", collection_name))
        self.collections[collection_name] = SimpleNamespace(
            config=SimpleNamespace(params=SimpleNamespace(vectors=vectors_config))
        )
        self.points[collection_name] = {}

    async def scroll(self, collection_name, **kwargs):
        self.calls.append(("scroll", collection_name))
        selector = kwargs["scroll_filter"].must[0]
        key, value = selector.key, selector.match.value
        found = [
            SimpleNamespace(id=point_id)
            for point_id, point in self.points[collection_name].items()
            if point.payload.get(key) == value
        ]
        return found, None

    async def upsert(self, collection_name, *, points, wait=True):
        self.calls.append(("upsert", collection_name))
        target = self.points[collection_name]
        for point in points:
            target[str(point.id)] = SimpleNamespace(
                id=str(point.id), vector=list(point.vector), payload=dict(point.payload)
            )

    async def delete(self, collection_name, *, points_selector, wait=True):
        self.calls.append(("delete", collection_name))
        target = self.points[collection_name]
        if hasattr(points_selector, "points"):
            for point_id in points_selector.points:
                target.pop(str(point_id), None)
        else:
            selector = points_selector.filter.must[0]
            for point_id, point in list(target.items()):
                if point.payload.get(selector.key) == selector.match.value:
                    target.pop(point_id, None)

    async def query_points(self, collection_name, **kwargs):
        self.calls.append(("query_points", collection_name))
        query_filter = kwargs["query_filter"]
        matches = []
        for point in self.points[collection_name].values():
            if all(
                point.payload.get(condition.key) == condition.match.value
                for condition in query_filter.must
            ):
                dot = sum(left * right for left, right in zip(kwargs["query"], point.vector))
                norm_q = math.sqrt(sum(value * value for value in kwargs["query"]))
                norm_p = math.sqrt(sum(value * value for value in point.vector))
                score = dot / (norm_q * norm_p)
                matches.append(SimpleNamespace(id=point.id, payload=point.payload, score=score))
        matches.sort(key=lambda point: point.score, reverse=True)
        return SimpleNamespace(points=matches[:kwargs["limit"]])

    async def close(self):
        return None


class IndexingSearchFlowTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.private_pem = cls.private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        cls.public_pem = cls.private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

    async def asyncSetUp(self):
        self._preexisting_redis_modules = {
            name for name in sys.modules
            if name == "redis" or name.startswith("redis.")
        }
        self.app, settings_module, dependencies = _load_search_app()
        self.settings = settings_module.SearchSettings(
            _env_file=None,
            internal_principal_public_key=self.public_pem,
            qdrant_collection_name="flow_test_collection",
            qdrant_url="http://qdrant.invalid",
            embedding_provider="openai",
            embedding_model="flow-test-model",
            embedding_dimensions=3,
            transcript_chunk_max_characters=16,
        )
        self.app.dependency_overrides[settings_module.get_settings] = lambda: self.settings
        embedding_contracts = importlib.import_module("embeddings.contracts")
        self.identity = embedding_contracts.EmbeddingModelIdentity(
            provider="openai", model="flow-test-model", dimensions=3,
        )
        self.provider = DeterministicEmbeddingProvider(self.identity)
        embeddings = importlib.import_module("embeddings.service").EmbeddingService(
            self.provider, self.identity,
        )
        self.qdrant = InMemoryQdrantClient()
        repository_type = importlib.import_module("vectorstore.qdrant_store").QdrantVectorRepository
        self.repository = repository_type(self.settings, client=self.qdrant)
        indexing_type = importlib.import_module("indexing.service").TranscriptIndexingService
        search_type = importlib.import_module("retrieval.semantic_search").SemanticSearch
        self.indexing = indexing_type(embeddings, self.repository, self.settings)
        # Use a distinct EmbeddingService/provider instance for query requests while
        # sharing the exact repository/client and deterministic vector convention.
        query_provider = DeterministicEmbeddingProvider(self.identity)
        query_embeddings = importlib.import_module("embeddings.service").EmbeddingService(
            query_provider, self.identity,
        )
        self.query_provider = query_provider
        self.search_service = search_type(query_embeddings, self.repository, self.settings)
        self.app.dependency_overrides[dependencies.get_transcript_indexing_service] = lambda: self.indexing
        self.app.dependency_overrides[dependencies.get_semantic_search_service] = lambda: self.search_service
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app, raise_app_exceptions=False),
            base_url="http://testserver",
        )
        self.owner_a = uuid4()
        self.owner_b = uuid4()
        self.org_id = uuid4()

    async def asyncTearDown(self):
        await self.client.aclose()
        self.app.dependency_overrides.clear()
        # qdrant-client.models imports its optional Redis support module. Keep
        # this test from affecting unrelated tests that assert Celery import
        # does not eagerly load Redis.
        for name in list(sys.modules):
            if (
                (name == "redis" or name.startswith("redis."))
                and name not in self._preexisting_redis_modules
            ):
                del sys.modules[name]

    def token(self, owner_id: UUID, *, audience="search-service", private_key=None):
        now = datetime.now(timezone.utc)
        return jwt.encode(
            {
                "sub": str(owner_id), "type": "internal_principal",
                "iss": "gateway-service", "aud": audience,
                "iat": now - timedelta(seconds=1),
                "exp": now + timedelta(minutes=1),
            },
            private_key or self.private_pem,
            algorithm="RS256",
        )

    @staticmethod
    def source(meeting_id, transcript_id, segments):
        now = datetime.now(timezone.utc)
        transcript = importlib.import_module("shared.schemas.transcript").TranscriptInDB(
            id=str(transcript_id), meeting_id=str(meeting_id), segments=segments,
            language="en", created_at=now, updated_at=now,
        )
        source_contract = importlib.import_module(
            "shared.schemas.transcript_indexing"
        ).TranscriptIndexSource
        return source_contract(transcript=transcript, organization_id=uuid4())

    async def index(self, owner_id, meeting_id, transcript_id, segments):
        return await self.client.post(
            f"/search/meetings/{meeting_id}/index",
            json=self.source(meeting_id, transcript_id, segments).model_dump(mode="json"),
            headers={"Authorization": f"Bearer {self.token(owner_id)}"},
        )

    async def search_request(self, owner_id, query, *, token=None, top_k=10):
        return await self.client.post(
            "/search",
            json={"query": query, "top_k": top_k},
            headers={"Authorization": f"Bearer {token or self.token(owner_id)}"},
        )

    async def test_index_then_search_returns_provenance_and_same_owner_multiple_meetings(self):
        meeting_a, meeting_b, transcript_a, transcript_b = (uuid4() for _ in range(4))
        meeting_b_owner, transcript_b_owner = uuid4(), uuid4()
        segments_a = [
            {"index": 0, "speaker": "Ada", "text": "budget approval", "start_ms": 10, "end_ms": 20},
            {"index": 1, "speaker": "Lin", "text": "retired detail", "start_ms": 30, "end_ms": 45},
        ]
        response_a = await self.index(self.owner_a, meeting_a, transcript_a, segments_a)
        response_b = await self.index(
            self.owner_a, meeting_b, transcript_b,
            [{"index": 0, "speaker": "Grace", "text": "budget project plan", "start_ms": 50, "end_ms": 70}],
        )
        response_other = await self.index(
            self.owner_b, meeting_b_owner, transcript_b_owner,
            [{"index": 0, "speaker": "Other", "text": "budget confidential", "start_ms": 5, "end_ms": 12}],
        )
        self.assertEqual(response_a.status_code, 200, response_a.text)
        self.assertEqual(response_b.status_code, 200, response_b.text)
        self.assertEqual(response_other.status_code, 200, response_other.text)
        self.assertEqual(response_a.json()["chunk_count"], 2)

        result = await self.search_request(self.owner_a, "budget project", top_k=2)
        self.assertEqual(result.status_code, 200, result.text)
        results = result.json()["results"]
        self.assertEqual({item["meeting_id"] for item in results}, {str(meeting_a), str(meeting_b)})
        self.assertNotIn(str(meeting_b_owner), {item["meeting_id"] for item in results})
        point_id = importlib.import_module("chunking.transcript_chunker").transcript_chunk_id(
            meeting_a, transcript_a, 0,
        )
        result_a = next(item for item in results if item["meeting_id"] == str(meeting_a))
        result_b = next(item for item in results if item["meeting_id"] == str(meeting_b))
        self.assertEqual(result_a["transcript_id"], str(transcript_a))
        self.assertEqual(result_b["transcript_id"], str(transcript_b))
        self.assertEqual(result_a["chunk_id"], str(point_id))
        self.assertEqual(result_a["chunk_index"], 0)
        self.assertEqual(result_a["text"], "budget approval")
        self.assertEqual(result_a["source_segments"][0]["speaker"], "Ada")
        self.assertEqual(result_a["source_segments"][0]["start_ms"], 10)
        self.assertAlmostEqual(result_a["score"], 1.0)
        point_b_id = importlib.import_module("chunking.transcript_chunker").transcript_chunk_id(
            meeting_b, transcript_b, 0,
        )
        self.assertEqual(result_b["chunk_id"], str(point_b_id))
        self.assertEqual(result_b["source_segments"][0]["speaker"], "Grace")
        self.assertAlmostEqual(result_b["score"], 1.0)

        # Replacing a different meeting with fewer chunks must leave this
        # meeting's deterministic point and search result intact.
        replacement = await self.index(
            self.owner_a, meeting_a, transcript_a,
            [{"index": 0, "speaker": "Ada", "text": "budget finalized", "start_ms": 10, "end_ms": 20}],
        )
        self.assertEqual(replacement.status_code, 200, replacement.text)
        after_replacement = await self.search_request(self.owner_a, "budget project", top_k=10)
        self.assertEqual(
            {item["meeting_id"] for item in after_replacement.json()["results"]},
            {str(meeting_a), str(meeting_b)},
        )
        self.assertIn(
            str(point_b_id),
            {item["chunk_id"] for item in after_replacement.json()["results"]},
        )

        # Meeting-scoped cleanup must not remove another meeting's points.
        await self.repository.delete_meeting(meeting_a)
        after_delete = await self.search_request(self.owner_a, "budget project", top_k=10)
        self.assertEqual(
            {item["meeting_id"] for item in after_delete.json()["results"]},
            {str(meeting_b)},
        )
        self.assertEqual(
            {item["chunk_id"] for item in after_delete.json()["results"]},
            {str(point_b_id)},
        )

        owner_b_search = await self.search_request(self.owner_b, "budget")
        self.assertEqual(owner_b_search.status_code, 200, owner_b_search.text)
        self.assertEqual(
            {item["meeting_id"] for item in owner_b_search.json()["results"]},
            {str(meeting_b_owner)},
        )

    async def test_replacement_prunes_stale_chunks_from_subsequent_search(self):
        meeting_id, transcript_id = uuid4(), uuid4()
        original = [
            {"index": 0, "text": "budget approval"},
            {"index": 1, "text": "retired detail"},
        ]
        first = await self.index(self.owner_a, meeting_id, transcript_id, original)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["chunk_count"], 2)

        replaced = await self.index(
            self.owner_a, meeting_id, transcript_id,
            [{"index": 0, "text": "budget approval updated"}],
        )
        self.assertEqual(replaced.status_code, 200, replaced.text)
        self.assertEqual(replaced.json()["chunk_count"], 1)
        stale_id = importlib.import_module("chunking.transcript_chunker").transcript_chunk_id(
            meeting_id, transcript_id, 1,
        )
        self.assertNotIn(str(stale_id), self.qdrant.points[self.settings.qdrant_collection_name])
        retired = await self.search_request(self.owner_a, "retired")
        self.assertEqual(retired.status_code, 200, retired.text)
        self.assertNotIn(
            "retired detail",
            [item["text"] for item in retired.json()["results"]],
        )
        self.assertNotIn(
            str(stale_id),
            [item["chunk_id"] for item in retired.json()["results"]],
        )

    async def test_empty_replacement_removes_points_but_invalid_principal_never_indexes(self):
        meeting_id, transcript_id = uuid4(), uuid4()
        first = await self.index(
            self.owner_a, meeting_id, transcript_id,
            [{"index": 0, "text": "budget approval"}],
        )
        self.assertEqual(first.status_code, 200, first.text)
        empty = await self.index(self.owner_a, meeting_id, transcript_id, [])
        self.assertEqual(empty.status_code, 200, empty.text)
        self.assertEqual(empty.json()["status"], "empty")
        self.assertEqual(empty.json()["chunk_count"], 0)
        budget = await self.search_request(self.owner_a, "budget")
        self.assertEqual(budget.json(), {"results": []})

        qdrant_calls_before = list(self.qdrant.calls)
        provider_requests_before = len(self.provider.requests)
        forged_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        forged_pem = forged_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        invalid = await self.client.post(
            "/search", json={"query": "budget"},
            headers={"Authorization": f"Bearer {self.token(self.owner_a, audience='meeting-service')}"},
        )
        self.assertEqual(invalid.status_code, 401)
        forged_index = await self.client.post(
            f"/search/meetings/{uuid4()}/index",
            json=self.source(uuid4(), uuid4(), [{"index": 0, "text": "budget"}]).model_dump(mode="json"),
            headers={"Authorization": f"Bearer {self.token(self.owner_a, private_key=forged_pem)}"},
        )
        self.assertEqual(forged_index.status_code, 401)
        self.assertEqual(len(self.provider.requests), provider_requests_before)
        self.assertEqual(self.qdrant.calls, qdrant_calls_before)

    async def test_embedding_failure_does_not_mutate_real_repository_projection(self):
        calls_before = list(self.qdrant.calls)
        self.provider.failure = RuntimeError("provider private detail")
        response = await self.index(
            self.owner_a, uuid4(), uuid4(), [{"index": 0, "text": "budget"}],
        )
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private detail", response.text)
        self.assertEqual(self.qdrant.calls, calls_before)


if __name__ == "__main__":
    unittest.main()
