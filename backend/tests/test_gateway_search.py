"""Gateway semantic-search authentication and proxy tests."""

from __future__ import annotations

import importlib
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

BACKEND_ROOT = Path(__file__).resolve().parents[1]
GATEWAY_ROOT = BACKEND_ROOT / "gateway-service"


def _load_gateway_app() -> tuple[FastAPI, object, object, object]:
    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            del sys.modules[module_name]
    for service in ("gateway-service", "meeting-service", "ai-service", "search-service"):
        root = str(BACKEND_ROOT / service)
        while root in sys.path:
            sys.path.remove(root)
    sys.path[:0] = [str(GATEWAY_ROOT), str(BACKEND_ROOT)]
    main = importlib.import_module("app.main")
    route = importlib.import_module("app.routes.search")
    auth = importlib.import_module("app.auth.dependencies")
    client_module = importlib.import_module("app.services.search_client")
    return main.app, route, auth, client_module


class GatewaySearchTests(unittest.TestCase):
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

    def test_gateway_client_signs_search_audience_and_forwards_only_request_id(self):
        _app, _route, _auth, client_module = _load_gateway_app()
        from shared.security.internal_principal import verify_internal_principal
        from shared.schemas.semantic_search import SemanticSearchRequest

        settings = importlib.import_module("app.config.settings").GatewaySettings(
            _env_file=None,
            internal_principal_private_key=SecretStr(self.private_pem),
        )
        search_client = client_module.SearchServiceClient(settings)
        response = SimpleNamespace(status_code=200, json=lambda: {"results": []})
        downstream = MagicMock()
        downstream.post = AsyncMock(return_value=response)
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=downstream)
        context.__aexit__ = AsyncMock(return_value=False)
        user_id = uuid.uuid4()

        async def run():
            with patch("httpx.AsyncClient", return_value=context) as constructor:
                result = await search_client.search(
                    SemanticSearchRequest(query="budget"),
                    user_id=user_id,
                    request_id="search-request-123",
                )
            return result, constructor

        import asyncio
        result, constructor = asyncio.run(run())
        self.assertEqual(result.results, [])
        self.assertEqual(constructor.call_args.kwargs["base_url"], settings.search_service_url)
        self.assertEqual(
            constructor.call_args.kwargs["timeout"], settings.search_service_timeout_seconds
        )
        downstream.post.assert_awaited_once()
        path = downstream.post.await_args.args[0]
        kwargs = downstream.post.await_args.kwargs
        self.assertEqual(path, "/search")
        self.assertEqual(kwargs["json"], {"query": "budget", "top_k": 10})
        headers = kwargs["headers"]
        token = headers["Authorization"].removeprefix("Bearer ")
        self.assertEqual(headers["X-Request-ID"], "search-request-123")
        principal = verify_internal_principal(
            token,
            public_key=self.public_pem,
            algorithm="RS256",
            issuer="gateway-service",
            audience="search-service",
        )
        self.assertEqual(principal, user_id)
        self.assertEqual(set(headers), {"Authorization", "X-Request-ID"})

    def test_gateway_client_forwards_meeting_filter_without_changing_owner_auth(self):
        _app, _route, _auth, client_module = _load_gateway_app()
        from shared.security.internal_principal import verify_internal_principal
        from shared.schemas.semantic_search import SemanticSearchRequest
        settings = importlib.import_module("app.config.settings").GatewaySettings(
            _env_file=None,
            internal_principal_private_key=SecretStr(self.private_pem),
        )
        client = client_module.SearchServiceClient(settings)
        meeting_id, user_id = uuid.uuid4(), uuid.uuid4()
        downstream = MagicMock()
        downstream.post = AsyncMock(return_value=SimpleNamespace(
            status_code=200, json=lambda: {"results": []}
        ))
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=downstream)
        context.__aexit__ = AsyncMock(return_value=False)

        async def run():
            with patch("httpx.AsyncClient", return_value=context):
                await client.search(
                    SemanticSearchRequest(query="budget", meeting_ids=[meeting_id]),
                    user_id=user_id,
                    request_id="month-filter-request",
                )

        import asyncio
        asyncio.run(run())
        kwargs = downstream.post.await_args.kwargs
        self.assertEqual(kwargs["json"]["meeting_ids"], [str(meeting_id)])
        token = kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        self.assertEqual(verify_internal_principal(
            token, public_key=self.public_pem, algorithm="RS256",
            issuer="gateway-service", audience="search-service",
        ), user_id)
        self.assertEqual(kwargs["headers"]["X-Request-ID"], "month-filter-request")

    def test_index_client_signs_search_audience_and_forwards_source_without_owner(self):
        _app, _route, _auth, client_module = _load_gateway_app()
        from shared.schemas.transcript_indexing import TranscriptIndexSource
        from shared.schemas.transcript import TranscriptInDB

        now = datetime.now(timezone.utc)
        meeting_id, transcript_id, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        source = TranscriptIndexSource(
            transcript=TranscriptInDB(
                id=str(transcript_id), meeting_id=str(meeting_id), segments=[],
                language="en", created_at=now, updated_at=now,
            ),
            organization_id=uuid.uuid4(),
        )
        settings = importlib.import_module("app.config.settings").GatewaySettings(
            _env_file=None,
            internal_principal_private_key=SecretStr(self.private_pem),
        )
        search_client = client_module.SearchServiceClient(settings)
        response = SimpleNamespace(status_code=200, json=lambda: {
            "meeting_id": str(meeting_id), "transcript_id": str(transcript_id),
            "status": "empty", "chunk_count": 0,
        })
        downstream = MagicMock()
        downstream.post = AsyncMock(return_value=response)
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=downstream)
        context.__aexit__ = AsyncMock(return_value=False)

        async def run():
            with patch("httpx.AsyncClient", return_value=context) as constructor:
                result = await search_client.index_transcript(
                    meeting_id, source, user_id=user_id, request_id="index-client-1",
                )
            return result, constructor

        import asyncio
        result, constructor = asyncio.run(run())
        self.assertEqual(result.status, "empty")
        self.assertEqual(
            constructor.call_args.kwargs["timeout"],
            settings.search_service_index_timeout_seconds,
        )
        kwargs = downstream.post.await_args.kwargs
        self.assertEqual(downstream.post.await_args.args[0], f"/search/meetings/{meeting_id}/index")
        self.assertNotIn("owner_id", kwargs["json"])
        token = kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        from shared.security.internal_principal import verify_internal_principal
        self.assertEqual(
            verify_internal_principal(
                token, public_key=self.public_pem, algorithm="RS256",
                issuer="gateway-service", audience="search-service",
            ),
            user_id,
        )

    def test_public_gateway_route_uses_authenticated_user_not_client_identity_headers(self):
        app, route, auth, _client_module = _load_gateway_app()
        from shared.database.models.user import User
        from shared.schemas.semantic_search import SemanticSearchResponse

        now = datetime.now(timezone.utc)
        authenticated_user = User(
            id=uuid.uuid4(), email="search-owner@example.com", password_hash="hash",
            created_at=now, updated_at=now,
        )

        class FakeSearchClient:
            def __init__(self):
                self.calls = []

            async def search(self, payload, *, user_id, request_id):
                self.calls.append((payload, user_id, request_id))
                return SemanticSearchResponse(results=[])

        fake_client = FakeSearchClient()
        app.dependency_overrides[auth.get_current_user] = lambda: authenticated_user
        app.dependency_overrides[route.get_search_client] = lambda: fake_client
        client = TestClient(app, raise_server_exceptions=False)
        try:
            response = client.post(
                "/api/v1/search",
                json={"query": "budget", "top_k": 4},
                headers={
                    "X-User-ID": str(uuid.uuid4()),
                    "X-Request-ID": "gateway-search-123",
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(fake_client.calls[0][1], authenticated_user.id)
            self.assertEqual(fake_client.calls[0][2], "gateway-search-123")
            self.assertEqual(response.json(), {"results": []})

            rejected = client.post(
                "/api/v1/search",
                json={"query": "budget", "owner_id": str(uuid.uuid4())},
            )
            self.assertEqual(rejected.status_code, 422)
            self.assertEqual(len(fake_client.calls), 1)
        finally:
            client.close()
            app.dependency_overrides.clear()

    def test_index_route_fetches_owned_source_then_forwards_authenticated_owner(self):
        app, route, auth, _client_module = _load_gateway_app()
        meeting_routes = importlib.import_module("app.routes.meetings")
        from shared.database.models.user import User
        from shared.schemas.transcript_indexing import TranscriptIndexingResult

        now = datetime.now(timezone.utc)
        user = User(id=uuid.uuid4(), email="index-owner@example.com", password_hash="hash", created_at=now, updated_at=now)
        meeting_id = uuid.uuid4()
        source = SimpleNamespace(model_dump=lambda **_kwargs: {"transcript": {"id": "t"}, "organization_id": str(uuid.uuid4())})

        class MeetingClient:
            calls = []
            error = None
            async def get_transcript_index_source(self, requested_id, *, user_id, request_id):
                self.calls.append((requested_id, user_id, request_id))
                if self.error is not None:
                    raise self.error
                return source

        class SearchClient:
            calls = []
            async def index_transcript(self, requested_id, source_arg, *, user_id, request_id):
                self.calls.append((requested_id, source_arg, user_id, request_id))
                return TranscriptIndexingResult(meeting_id=requested_id, transcript_id=uuid.uuid4(), status="indexed", chunk_count=1)

        meeting_client, search_client = MeetingClient(), SearchClient()
        app.dependency_overrides[auth.get_current_user] = lambda: user
        app.dependency_overrides[meeting_routes.get_meeting_client] = lambda: meeting_client
        app.dependency_overrides[route.get_search_client] = lambda: search_client
        client = TestClient(app, raise_server_exceptions=False)
        try:
            response = client.post(
                f"/api/v1/search/meetings/{meeting_id}/index",
                json={"owner_id": str(uuid.uuid4())},
                headers={"X-Request-ID": "index-req"},
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(meeting_client.calls, [(str(meeting_id), user.id, "index-req")])
            self.assertEqual(search_client.calls, [(meeting_id, source, user.id, "index-req")])
            from shared.exceptions.common import NotFoundError
            meeting_client.error = NotFoundError("Transcript not found.")
            missing = client.post(f"/api/v1/search/meetings/{meeting_id}/index")
            self.assertEqual(missing.status_code, 404, missing.text)
            self.assertEqual(len(search_client.calls), 1)
            from shared.exceptions.common import ForbiddenError
            meeting_client.error = ForbiddenError()
            forbidden = client.post(f"/api/v1/search/meetings/{meeting_id}/index")
            self.assertEqual(forbidden.status_code, 403, forbidden.text)
            self.assertEqual(len(search_client.calls), 1)
        finally:
            client.close()
            app.dependency_overrides.clear()

    def test_missing_or_invalid_external_credentials_never_call_search_service(self):
        app, route, _auth, _client_module = _load_gateway_app()
        from shared.database.session import get_db_session

        class FakeSearchClient:
            def __init__(self):
                self.calls = []

            async def search(self, payload, *, user_id, request_id):
                self.calls.append((payload, user_id, request_id))
                raise AssertionError("Search must not run for unauthenticated requests")

        async def fake_session():
            yield object()

        fake_client = FakeSearchClient()
        app.dependency_overrides[get_db_session] = fake_session
        app.dependency_overrides[route.get_search_client] = lambda: fake_client
        client = TestClient(app, raise_server_exceptions=False)
        try:
            for headers in (
                {"X-User-ID": str(uuid.uuid4())},
                {
                    "Authorization": "Bearer malformed-external-token",
                    "X-User-ID": str(uuid.uuid4()),
                },
            ):
                with self.subTest(has_authorization="Authorization" in headers):
                    response = client.post(
                        "/api/v1/search",
                        json={"query": "budget"},
                        headers=headers,
                    )
                    self.assertEqual(response.status_code, 401)
        finally:
            client.close()
            app.dependency_overrides.clear()
        self.assertEqual(fake_client.calls, [])

    def test_timeout_and_non_success_downstream_responses_are_sanitized(self):
        _app, _route, _auth, client_module = _load_gateway_app()
        import asyncio
        import httpx
        from shared.exceptions.common import ServiceUnavailableError, ValidationError
        from shared.schemas.semantic_search import SemanticSearchRequest

        settings = importlib.import_module("app.config.settings").GatewaySettings(
            _env_file=None,
        )
        search_client = client_module.SearchServiceClient(settings)
        cases = (
            (
                "timeout",
                httpx.TimeoutException("authorization=do-not-leak"),
                None,
                ServiceUnavailableError,
            ),
            (
                "upstream failure",
                None,
                SimpleNamespace(
                    status_code=502,
                    json=lambda: {"error": "provider-key=do-not-leak"},
                ),
                ServiceUnavailableError,
            ),
            (
                "redirect",
                None,
                SimpleNamespace(status_code=302, json=lambda: {"results": []}),
                ServiceUnavailableError,
            ),
            (
                "downstream validation",
                None,
                SimpleNamespace(
                    status_code=422,
                    json=lambda: {"detail": "private downstream detail"},
                ),
                ValidationError,
            ),
        )
        for label, error, response, expected_error in cases:
            with self.subTest(label=label):
                downstream = MagicMock()
                if error is not None:
                    downstream.post = AsyncMock(side_effect=error)
                else:
                    downstream.post = AsyncMock(return_value=response)
                context = MagicMock()
                context.__aenter__ = AsyncMock(return_value=downstream)
                context.__aexit__ = AsyncMock(return_value=False)

                async def invoke():
                    with patch("httpx.AsyncClient", return_value=context):
                        return await search_client.search(
                            SemanticSearchRequest(query="budget"),
                            user_id=uuid.uuid4(),
                            request_id="safe-search-error",
                        )

                with self.assertRaises(expected_error) as raised:
                    asyncio.run(invoke())
                self.assertNotIn("do-not-leak", str(raised.exception))
                self.assertNotIn("private downstream detail", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
