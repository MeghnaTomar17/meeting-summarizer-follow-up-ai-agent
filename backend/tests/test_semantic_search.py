"""Authenticated semantic-retrieval tests with in-memory providers and Qdrant."""

from __future__ import annotations

import importlib
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
from pydantic import ValidationError


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SEARCH_ROOT = BACKEND_ROOT / "search-service"
OWNER_A = UUID("10000000-0000-0000-0000-000000000001")
OWNER_B = UUID("10000000-0000-0000-0000-000000000002")


def _load_search_app():
    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            del sys.modules[module_name]
        elif module_name.split(".", 1)[0] in {
            "chunking", "embeddings", "indexing", "retrieval", "vectorstore"
        }:
            del sys.modules[module_name]
    for service in ("gateway-service", "meeting-service", "ai-service", "search-service"):
        root = str(BACKEND_ROOT / service)
        while root in sys.path:
            sys.path.remove(root)
    sys.path[:0] = [str(SEARCH_ROOT), str(BACKEND_ROOT)]
    return (
        importlib.import_module("app.main").app,
        importlib.import_module("app.config.settings"),
        importlib.import_module("app.auth.dependencies"),
        importlib.import_module("app.dependencies"),
    )


class FakeEmbeddingProvider:
    def __init__(self, *, failure: Exception | None = None):
        self.failure = failure
        self.response_override = None
        self.requests = []

    async def embed(self, request):
        self.requests.append(request)
        if self.failure:
            raise self.failure
        if self.response_override is not None:
            return self.response_override
        return importlib.import_module("embeddings.contracts").EmbeddingResponse(
            model_identity=request.model_identity,
            vectors=[[0.25, 0.5, 0.75]],
        )

    async def aclose(self):
        return None


class FakeSearchQdrantClient:
    def __init__(self, *, points=None, failure: Exception | None = None):
        from qdrant_client import models

        self.models = models
        self.collection = SimpleNamespace(
            config=SimpleNamespace(
                params=SimpleNamespace(
                    vectors=models.VectorParams(size=3, distance=models.Distance.COSINE)
                )
            )
        )
        self.points = points or []
        self.failure = failure
        self.collection_failure = None
        self.calls = []
        self.close_count = 0

    async def get_collection(self, collection_name):
        self.calls.append(("get_collection", collection_name))
        if self.collection_failure:
            raise self.collection_failure
        return self.collection

    async def query_points(self, collection_name, **kwargs):
        self.calls.append(("query_points", collection_name, kwargs))
        if self.failure:
            raise self.failure
        point_filter = kwargs["query_filter"]
        matches = [
            point for point in self.points
            if all(
                point.payload.get(condition.key) in condition.match.any
                if getattr(condition.match, "any", None) is not None
                else point.payload.get(condition.key) == condition.match.value
                for condition in point_filter.must
            )
        ]
        matches.sort(key=lambda point: point.score, reverse=True)
        return SimpleNamespace(points=matches[:kwargs["limit"]])

    async def close(self):
        self.close_count += 1


class SemanticSearchTests(unittest.IsolatedAsyncioTestCase):
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
        self.app, self.settings_module, self.auth_module, self.dependencies = _load_search_app()
        self.settings = self.settings_module.SearchSettings(
            _env_file=None,
            internal_principal_public_key=self.public_pem,
            qdrant_collection_name="configured_transcript_collection",
            qdrant_url="http://qdrant.invalid",
            embedding_provider="openai",
            embedding_model="unit-test-embeddings",
            embedding_dimensions=3,
        )
        self.app.dependency_overrides[self.settings_module.get_settings] = lambda: self.settings
        self.owner_a_point = self._point(OWNER_A, score=0.91)
        self.owner_b_point = self._point(OWNER_B, score=0.99)
        self.qdrant = FakeSearchQdrantClient(
            points=[self.owner_a_point, self.owner_b_point]
        )
        self.provider = FakeEmbeddingProvider()
        self.embedding_contracts = importlib.import_module("embeddings.contracts")
        self.embedding_service = importlib.import_module("embeddings.service").EmbeddingService(
            self.provider,
            self.embedding_contracts.EmbeddingModelIdentity(
                provider="openai", model="unit-test-embeddings", dimensions=3
            ),
        )
        self.repository = importlib.import_module("vectorstore.qdrant_store").QdrantVectorRepository(
            self.settings, client=self.qdrant
        )
        self.semantic_search = importlib.import_module("retrieval.semantic_search").SemanticSearch(
            self.embedding_service, self.repository, self.settings
        )
        self.app.dependency_overrides[self.dependencies.get_semantic_search_service] = (
            lambda: self.semantic_search
        )
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app, raise_app_exceptions=False),
            base_url="http://testserver",
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        self.app.dependency_overrides.clear()

    def _point(self, owner_id: UUID, *, score: float):
        from chunking.transcript_chunker import transcript_chunk_id

        meeting_id = uuid4()
        transcript_id = uuid4()
        chunk_id = transcript_chunk_id(meeting_id, transcript_id, 0)
        payload = {
            "schema_version": 1,
            "chunk_id": str(chunk_id),
            "meeting_id": str(meeting_id),
            "transcript_id": str(transcript_id),
            "owner_id": str(owner_id),
            "organization_id": str(uuid4()),
            "chunk_index": 0,
            "source_segments": [
                {"index": 0, "speaker": "Ada", "start_ms": 1200, "end_ms": 2400}
            ],
            "start_ms": 1200,
            "end_ms": 2400,
            "language": "en",
            "text": f"Private transcript excerpt for {owner_id}",
            "embedding_model": {
                "provider": "openai",
                "model": "unit-test-embeddings",
                "dimensions": 3,
            },
        }
        return SimpleNamespace(id=str(chunk_id), payload=payload, score=score)

    def _token(self, user_id=OWNER_A, *, audience="search-service", token_type="internal_principal",
               expires_at=None, private_key=None):
        now = datetime.now(timezone.utc)
        return jwt.encode(
            {
                "sub": str(user_id),
                "type": token_type,
                "iss": "gateway-service",
                "aud": audience,
                "iat": now - timedelta(seconds=1),
                "exp": expires_at or now + timedelta(minutes=1),
            },
            private_key or self.private_pem,
            algorithm="RS256",
        )

    async def _request(self, token=None, *, payload=None, headers=None):
        request_headers = dict(headers or {})
        if token:
            request_headers["Authorization"] = f"Bearer {token}"
        return await self.client.post(
            "/search",
            json=payload or {"query": "  budget decision  ", "top_k": 5},
            headers=request_headers,
        )

    async def test_contract_validation_defaults_and_forbidden_scope_fields(self):
        contract = importlib.import_module("shared.schemas.semantic_search")
        valid = contract.SemanticSearchRequest(query="  budget?  ")
        self.assertEqual(valid.query, "budget?")
        self.assertEqual(valid.top_k, 10)
        for invalid in (
            {"query": ""},
            {"query": "   "},
            {"query": "q" * 2001},
            {"query": "query", "top_k": 0},
            {"query": "query", "top_k": True},
            {"query": "query", "top_k": 1.5},
            {"query": "query", "top_k": "5"},
            {"query": "query", "top_k": 51},
            {"query": "query", "owner_id": str(OWNER_B)},
            {"query": "query", "organization_id": str(uuid4())},
            {"query": "query", "scope": {"owner_id": str(OWNER_B)}},
            {"query": "query", "filter": {"must": []}},
            {"query": "query", "meeting_ids": [str(OWNER_A), str(OWNER_A)]},
            {"query": "query", "meeting_ids": [str(uuid4()) for _ in range(101)]},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                contract.SemanticSearchRequest.model_validate(invalid)
        with self.assertRaises(ValidationError):
            contract.SemanticSearchResult(
                meeting_id=uuid4(), transcript_id=uuid4(), chunk_id=uuid4(),
                chunk_index=0, text="result", source_segments=[{"index": 0}],
                score=float("nan"),
            )

    async def test_search_configuration_has_public_verification_key_only_and_rejects_dev_key_in_production(self):
        from shared.config.base import AppEnv

        self.assertIn("internal_principal_public_key", self.settings_module.SearchSettings.model_fields)
        self.assertNotIn("internal_principal_private_key", self.settings_module.SearchSettings.model_fields)
        with self.assertRaises(ValidationError):
            self.settings_module.SearchSettings(
                _env_file=None,
                app_env=AppEnv.PRODUCTION,
            )
        accepted = self.settings_module.SearchSettings(
            _env_file=None,
            app_env=AppEnv.PRODUCTION,
            internal_principal_public_key=self.public_pem,
        )
        self.assertEqual(accepted.internal_principal_public_key, self.public_pem)

    async def test_authenticated_end_to_end_search_uses_mandatory_owner_filter(self):
        response = await self._request(
            self._token(),
            headers={
                "X-User-ID": str(OWNER_B),
                "X-Organization-ID": str(uuid4()),
                "X-Request-ID": "semantic-search-test",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers.get("X-Request-ID"), "semantic-search-test")
        body = response.json()
        self.assertEqual(len(body["results"]), 1)
        result = body["results"][0]
        self.assertEqual(result["chunk_id"], self.owner_a_point.id)
        self.assertEqual(result["source_segments"][0]["speaker"], "Ada")
        self.assertEqual(result["score"], 0.91)
        self.assertNotIn("owner_id", result)
        self.assertNotIn("organization_id", result)
        self.assertNotIn("embedding_model", result)
        self.assertNotIn("vector", result)
        self.assertEqual(self.provider.requests[0].texts, ["budget decision"])
        qdrant_call = next(call for call in self.qdrant.calls if call[0] == "query_points")
        self.assertEqual(qdrant_call[1], "configured_transcript_collection")
        self.assertEqual(qdrant_call[2]["limit"], 5)
        self.assertFalse(qdrant_call[2]["with_vectors"])
        condition = qdrant_call[2]["query_filter"].must[0]
        self.assertEqual(condition.key, "owner_id")
        self.assertEqual(condition.match.value, str(OWNER_A))

    async def test_meeting_filter_is_intersected_with_mandatory_owner_filter(self):
        allowed_id = UUID(self.owner_a_point.payload["meeting_id"])
        response = await self._request(
            self._token(), payload={"query": "budget", "meeting_ids": [str(allowed_id)]}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([item["meeting_id"] for item in response.json()["results"]], [str(allowed_id)])
        conditions = next(call for call in self.qdrant.calls if call[0] == "query_points")[2]["query_filter"].must
        self.assertEqual(conditions[0].key, "owner_id")
        self.assertEqual(conditions[0].match.value, str(OWNER_A))
        self.assertEqual(conditions[1].key, "meeting_id")
        self.assertEqual(conditions[1].match.any, [str(allowed_id)])

    async def test_empty_meeting_filter_returns_no_results_without_embedding_or_qdrant(self):
        response = await self._request(
            self._token(), payload={"query": "budget", "meeting_ids": []}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["results"], [])
        self.assertEqual(self.provider.requests, [])
        self.assertFalse(any(call[0] == "query_points" for call in self.qdrant.calls))

    async def test_missing_wrong_expired_wrong_purpose_and_forged_principals_fail_before_search(self):
        forged_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        forged_private = forged_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        expired = self._token(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        tokens = [
            None,
            "not-a-token",
            self._token(audience="meeting-service"),
            self._token(token_type="access"),
            expired,
            self._token(private_key=forged_private),
        ]
        for token in tokens:
            with self.subTest(token=token and token[:12]):
                response = await self._request(token)
                self.assertEqual(response.status_code, 401)
                self.assertNotIn("meeting", response.text.lower())
        self.assertEqual(self.provider.requests, [])
        no_token_with_identity = await self._request(
            headers={"X-User-ID": str(OWNER_A)}, payload={"query": "budget"}
        )
        self.assertEqual(no_token_with_identity.status_code, 401)
        self.assertFalse(any(call[0] == "query_points" for call in self.qdrant.calls))

    async def test_external_access_jwt_is_not_an_internal_principal(self):
        token = jwt.encode(
            {"sub": str(OWNER_A), "type": "access", "exp": datetime.now(timezone.utc) + timedelta(minutes=1)},
            "external-access-secret",
            algorithm="HS256",
        )
        self.assertEqual((await self._request(token)).status_code, 401)
        self.assertFalse(any(call[0] == "query_points" for call in self.qdrant.calls))

    async def test_scope_fields_in_body_are_rejected_before_embedding_or_qdrant(self):
        response = await self._request(
            self._token(),
            payload={"query": "budget", "owner_id": str(OWNER_B)},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.provider.requests, [])
        self.assertFalse(any(call[0] == "query_points" for call in self.qdrant.calls))

    async def test_no_authorized_matches_returns_empty_without_unfiltered_fallback(self):
        self.qdrant.points = [self.owner_b_point]
        response = await self._request(self._token())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"results": []})
        calls = [call for call in self.qdrant.calls if call[0] == "query_points"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2]["query_filter"].must[0].key, "owner_id")

    async def test_malformed_payload_and_invalid_score_fail_closed_with_sanitized_error(self):
        self.owner_a_point.payload = {"owner_id": str(OWNER_A)}
        response = await self._request(self._token())
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("Private transcript", response.text)

        self.owner_a_point = self._point(OWNER_A, score=float("inf"))
        self.qdrant.points = [self.owner_a_point]
        response = await self._request(self._token())
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("inf", response.text.lower())

    async def test_inconsistent_embedding_metadata_fails_closed(self):
        self.owner_a_point.payload["embedding_model"]["model"] = "stale-model"
        response = await self._request(self._token())
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("stale-model", response.text)

    async def test_provider_and_qdrant_failures_are_sanitized(self):
        self.provider.failure = RuntimeError("provider key=secret-value")
        response = await self._request(self._token())
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret-value", response.text)
        self.assertFalse(any(call[0] == "query_points" for call in self.qdrant.calls))

        self.provider.failure = None
        self.qdrant.failure = RuntimeError("qdrant api-key=vector-secret")
        response = await self._request(self._token())
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("vector-secret", response.text)

    async def test_wrong_embedding_identity_fails_before_qdrant(self):
        identity = self.embedding_contracts.EmbeddingModelIdentity(
            provider="openai", model="wrong-model", dimensions=3
        )
        self.provider.response_override = self.embedding_contracts.EmbeddingResponse(
            model_identity=identity, vectors=[[0.1, 0.2, 0.3]]
        )
        response = await self._request(self._token())
        self.assertEqual(response.status_code, 503)
        self.assertFalse(any(call[0] == "query_points" for call in self.qdrant.calls))

    async def test_missing_or_mismatched_collection_fails_without_search(self):
        from qdrant_client import models

        self.qdrant.collection_failure = RuntimeError("collection missing, token=secret")
        response = await self._request(self._token())
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret", response.text)
        self.assertFalse(any(call[0] == "query_points" for call in self.qdrant.calls))
        self.assertFalse(any(call[0] == "create_collection" for call in self.qdrant.calls))

        self.qdrant.collection_failure = None
        self.qdrant.collection.config.params.vectors = models.VectorParams(
            size=3, distance=models.Distance.DOT
        )
        response = await self._request(self._token())
        self.assertEqual(response.status_code, 503)
        self.assertFalse(any(call[0] == "query_points" for call in self.qdrant.calls))


if __name__ == "__main__":
    unittest.main()
