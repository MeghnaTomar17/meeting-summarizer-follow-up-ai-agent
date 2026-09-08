"""API tests for authenticated user self-service endpoints."""

from __future__ import annotations

import importlib
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
GATEWAY_ROOT = BACKEND_ROOT / "gateway-service"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _load_gateway_app() -> tuple[FastAPI, object, object]:
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]
    while str(GATEWAY_ROOT) in sys.path:
        sys.path.remove(str(GATEWAY_ROOT))
    sys.path.insert(0, str(GATEWAY_ROOT))
    main = importlib.import_module("app.main")
    users = importlib.import_module("app.routes.users")
    auth = importlib.import_module("app.auth.dependencies")
    return main.app, users.get_user_service, auth.get_current_user


class UserRouteTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.app, self.service_dependency, self.auth_dependency = _load_gateway_app()
        from shared.database.models.user import User
        from shared.schemas.user import UserPublic

        now = datetime.now(timezone.utc)
        self.user = User(
            id=uuid.uuid4(),
            email="owner@example.com",
            password_hash="persisted-hash",
            created_at=now,
            updated_at=now,
        )
        self.UserPublic = UserPublic
        self.service = MagicMock()
        self.service.get_current_user = AsyncMock(return_value=self._public_user())
        self.service.update_current_user = AsyncMock(return_value=self._public_user("new@example.com"))
        self.app.dependency_overrides[self.service_dependency] = lambda: self.service
        self.app.dependency_overrides[self.auth_dependency] = lambda: self.user
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def tearDown(self) -> None:
        self.client.close()
        self.app.dependency_overrides.clear()

    def _public_user(self, email: str = "owner@example.com") -> object:
        return self.UserPublic(
            id=str(self.user.id),
            email=email,
            created_at=self.user.created_at,
        )

    def test_self_service_routes_are_mounted_under_api_v1(self) -> None:
        paths = {route.path for route in self.app.routes}

        self.assertIn("/api/v1/auth/me", paths)
        self.assertIn("/api/v1/users/me", paths)
        self.assertNotIn("/auth/me", paths)
        self.assertNotIn("/users/me", paths)

    def test_auth_me_and_users_me_return_safe_authenticated_profile(self) -> None:
        for path in ("/api/v1/auth/me", "/api/v1/users/me"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["id"], str(self.user.id))
                self.assertEqual(response.json()["email"], "owner@example.com")
                self.assertNotIn("password_hash", response.json())

        self.assertEqual(self.service.get_current_user.await_count, 2)
        self.service.get_current_user.assert_awaited_with(self.user)

    def test_missing_authentication_returns_standard_401(self) -> None:
        from shared.database.session import get_db_session

        self.app.dependency_overrides.pop(self.auth_dependency)
        self.app.dependency_overrides[get_db_session] = lambda: MagicMock()
        response = self.client.get("/api/v1/users/me")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "UNAUTHORIZED")
        self.service.get_current_user.assert_not_called()

    def test_patch_updates_only_authenticated_user(self) -> None:
        response = self.client.patch(
            "/api/v1/users/me",
            json={"email": " NEW@Example.COM "},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(self.user.id))
        payload = self.service.update_current_user.await_args.args[1]
        self.assertEqual(str(payload.email), "NEW@example.com")
        self.service.update_current_user.assert_awaited_once_with(self.user, payload)

    def test_patch_rejects_identity_and_sensitive_fields(self) -> None:
        for body in (
            {"email": "other@example.com", "user_id": str(uuid.uuid4())},
            {"email": "other@example.com", "password": "password1"},
            {"email": "other@example.com", "password_hash": "hash"},
        ):
            with self.subTest(body=body):
                response = self.client.patch("/api/v1/users/me", json=body)
                self.assertEqual(response.status_code, 422)

        self.service.update_current_user.assert_not_called()

    def test_patch_validation_and_conflict_use_standard_errors(self) -> None:
        invalid = self.client.patch("/api/v1/users/me", json={"email": "invalid"})
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(invalid.json()["error"]["code"], "VALIDATION_ERROR")

        from shared.exceptions.common import ConflictError

        self.service.update_current_user.side_effect = ConflictError("Email is already registered.")
        conflict = self.client.patch("/api/v1/users/me", json={"email": "other@example.com"})
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["error"]["code"], "CONFLICT")

    def test_unexpected_service_error_uses_safe_500_response(self) -> None:
        self.service.update_current_user.side_effect = RuntimeError("database password failure")

        response = self.client.patch("/api/v1/users/me", json={"email": "new@example.com"})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["message"], "An unexpected error occurred.")


if __name__ == "__main__":
    unittest.main()
