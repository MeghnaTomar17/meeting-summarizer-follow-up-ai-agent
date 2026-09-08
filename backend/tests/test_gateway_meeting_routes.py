"""Gateway Meeting facade tests using mocked authenticated service calls."""

from __future__ import annotations

import asyncio
import importlib
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr

BACKEND_ROOT = Path(__file__).resolve().parents[1]
GATEWAY_ROOT = BACKEND_ROOT / "gateway-service"


def _load_gateway_app() -> tuple[FastAPI, object, object]:
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]
    while str(GATEWAY_ROOT) in sys.path:
        sys.path.remove(str(GATEWAY_ROOT))
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    sys.path.insert(0, str(GATEWAY_ROOT))
    main = importlib.import_module("app.main")
    routes = importlib.import_module("app.routes.meetings")
    auth = importlib.import_module("app.auth.dependencies")
    return main.app, routes.get_meeting_client, auth.get_current_user


class GatewayMeetingRoutesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.app, client_dependency, self.auth_dependency = _load_gateway_app()
        from shared.database.models.user import User

        now = datetime.now(timezone.utc)
        self.user = User(id=uuid.uuid4(), email="owner@example.com", password_hash="hash", created_at=now, updated_at=now)
        self.meeting_client = MagicMock()
        self.meeting_client.create_meeting = AsyncMock()
        self.meeting_client.get_meeting = AsyncMock()
        self.app.dependency_overrides[client_dependency] = lambda: self.meeting_client
        self.app.dependency_overrides[self.auth_dependency] = lambda: self.user
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def tearDown(self) -> None:
        self.client.close()
        self.app.dependency_overrides.clear()

    def _meeting(self):
        from shared.schemas.meeting import MeetingPublic

        now = datetime.now(timezone.utc)
        return MeetingPublic(id=str(uuid.uuid4()), title="Planning", participants=[], status="pending", created_at=now, updated_at=now)

    def test_public_meeting_create_derives_owner_from_gateway_user(self) -> None:
        meeting = self._meeting()
        self.meeting_client.create_meeting.return_value = meeting
        response = self.client.post(
            "/api/v1/meetings",
            json={"organization_id": str(uuid.uuid4()), "title": "Planning", "created_by": str(uuid.uuid4())},
            headers={"X-Request-ID": "gateway-meeting-create"},
        )

        self.assertEqual(response.status_code, 422)
        self.meeting_client.create_meeting.assert_not_called()
        response = self.client.post(
            "/api/v1/meetings",
            json={"organization_id": str(uuid.uuid4()), "title": "Planning"},
            headers={"X-Request-ID": "gateway-meeting-create"},
        )
        self.assertEqual(response.status_code, 201)
        submitted = self.meeting_client.create_meeting.await_args.args[0]
        self.assertEqual(submitted.title, "Planning")
        self.assertEqual(self.meeting_client.create_meeting.await_args.kwargs["user_id"], self.user.id)
        self.assertEqual(self.meeting_client.create_meeting.await_args.kwargs["request_id"], "gateway-meeting-create")

    def test_gateway_forwards_owner_and_preserves_forbidden_response(self) -> None:
        from shared.exceptions.common import ForbiddenError

        self.meeting_client.get_meeting.side_effect = ForbiddenError()
        response = self.client.get(f"/api/v1/meetings/{uuid.uuid4()}")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["message"], "Forbidden.")
        self.assertNotIn(str(self.user.id), response.text)

    def test_missing_external_bearer_token_is_unauthorized(self) -> None:
        from shared.database.session import get_db_session

        self.app.dependency_overrides.pop(self.auth_dependency)
        self.app.dependency_overrides[get_db_session] = lambda: MagicMock()

        response = self.client.get(f"/api/v1/meetings/{uuid.uuid4()}")

        self.assertEqual(response.status_code, 401)
        self.meeting_client.get_meeting.assert_not_called()

    def test_client_sends_signed_internal_principal_and_request_id(self) -> None:
        client_module = importlib.import_module("app.services.meeting_client")
        from shared.security.internal_principal import verify_internal_principal

        key_pair = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_key = key_pair.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        public_key = key_pair.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

        settings = SimpleNamespace(
            meeting_service_url="http://meeting-service:8001",
            internal_principal_private_key=SecretStr(private_key),
            internal_principal_algorithm="RS256",
            internal_principal_issuer="gateway-service",
            internal_principal_expire_seconds=60,
        )
        service_client = client_module.MeetingServiceClient(settings)
        response = client_module.httpx.Response(200, json={"ok": True})
        transport = MagicMock()
        transport.request = AsyncMock(return_value=response)
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=transport)
        context.__aexit__ = AsyncMock(return_value=None)

        with patch.object(client_module.httpx, "AsyncClient", return_value=context):
            result = asyncio.run(
                service_client._request(
                    "GET",
                    "/meetings/example",
                    None,
                    self.user.id,
                    "correlation-id",
                )
            )

        self.assertEqual(result, {"ok": True})
        headers = transport.request.await_args.kwargs["headers"]
        self.assertEqual(headers["X-Request-ID"], "correlation-id")
        token = headers["Authorization"].removeprefix("Bearer ")
        self.assertEqual(
            verify_internal_principal(
                token,
                public_key=public_key,
                algorithm="RS256",
                issuer="gateway-service",
                audience="meeting-service",
            ),
            self.user.id,
        )
