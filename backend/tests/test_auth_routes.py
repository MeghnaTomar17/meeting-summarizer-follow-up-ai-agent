"""Route tests for Gateway public authentication endpoints."""

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


def _load_gateway_app() -> tuple[FastAPI, object]:
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]
    while str(GATEWAY_ROOT) in sys.path:
        sys.path.remove(str(GATEWAY_ROOT))
    sys.path.insert(0, str(GATEWAY_ROOT))

    main_module = importlib.import_module("app.main")
    auth_module = importlib.import_module("app.routes.auth")
    return main_module.app, auth_module.get_authentication_service


class AuthenticationRouteTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.app, self.service_dependency = _load_gateway_app()
        self.service = MagicMock()
        self.service.signup = AsyncMock()
        self.service.login = AsyncMock()
        self.service.refresh = AsyncMock()
        self.service.logout = AsyncMock()
        self.app.dependency_overrides[self.service_dependency] = lambda: self.service
        self.client = TestClient(self.app, raise_server_exceptions=False)

        from app.schemas.auth import TokenResponse
        from shared.exceptions.common import ConflictError, UnauthorizedError
        from shared.schemas.user import UserPublic

        self.TokenResponse = TokenResponse
        self.ConflictError = ConflictError
        self.UnauthorizedError = UnauthorizedError
        self.UserPublic = UserPublic

    def tearDown(self) -> None:
        self.app.dependency_overrides.clear()

    def _user_public(self) -> object:
        return self.UserPublic(
            id=str(uuid.uuid4()),
            email="user@example.com",
            created_at=datetime.now(timezone.utc),
        )

    def test_auth_router_is_mounted_under_api_v1(self) -> None:
        paths = {route.path for route in self.app.routes}
        self.assertIn("/api/v1/auth/signup", paths)
        self.assertIn("/api/v1/auth/login", paths)
        self.assertIn("/api/v1/auth/refresh", paths)
        self.assertIn("/api/v1/auth/logout", paths)

    def test_signup_returns_safe_public_user(self) -> None:
        user = self._user_public()
        self.service.signup.return_value = user

        response = self.client.post(
            "/api/v1/auth/signup",
            json={"email": "user@example.com", "password": "password1"},
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["email"], "user@example.com")
        self.assertNotIn("password_hash", response.json())
        payload = self.service.signup.await_args.args[0]
        self.assertEqual(str(payload.email), "user@example.com")
        self.assertEqual(payload.password, "password1")

    def test_login_returns_token_response(self) -> None:
        self.service.login.return_value = self.TokenResponse(access_token="signed-token", refresh_token="opaque-token")

        response = self.client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "password1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"access_token": "signed-token", "refresh_token": "opaque-token", "token_type": "bearer"})
        payload = self.service.login.await_args.args[0]
        self.assertEqual(str(payload.email), "user@example.com")

    def test_refresh_uses_refresh_body_without_access_authorization(self) -> None:
        from app.schemas.auth import RefreshRequest

        self.service.refresh.return_value = self.TokenResponse(
            access_token="new-access", refresh_token="new-refresh"
        )
        response = self.client.post(
            "/api/v1/auth/refresh", json={"refresh_token": "opaque-refresh"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["refresh_token"], "new-refresh")
        self.assertEqual(
            self.service.refresh.await_args.args[0],
            RefreshRequest(refresh_token="opaque-refresh"),
        )

    def test_refresh_and_logout_reject_extra_request_fields(self) -> None:
        for endpoint in ("refresh", "logout"):
            with self.subTest(endpoint=endpoint):
                response = self.client.post(
                    f"/api/v1/auth/{endpoint}",
                    json={"refresh_token": "opaque-refresh", "user_id": "attacker"},
                )
                self.assertEqual(response.status_code, 422)
        for token in ("", "x" * 513):
            with self.subTest(token_length=len(token)):
                response = self.client.post(
                    "/api/v1/auth/refresh", json={"refresh_token": token}
                )
                self.assertEqual(response.status_code, 422)
        self.service.refresh.assert_not_called()

    def test_signup_validation_error_uses_standard_response_and_request_id(self) -> None:
        response = self.client.post(
            "/api/v1/auth/signup",
            json={"email": "invalid", "password": "short"},
            headers={"X-Request-ID": "auth-validation"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")
        self.assertEqual(response.json()["error"]["request_id"], "auth-validation")
        self.assertEqual(response.headers["X-Request-ID"], "auth-validation")
        self.service.signup.assert_not_called()

    def test_duplicate_signup_uses_standard_conflict_response(self) -> None:
        self.service.signup.side_effect = self.ConflictError("Email is already registered.")

        response = self.client.post(
            "/api/v1/auth/signup",
            json={"email": "user@example.com", "password": "password1"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "CONFLICT")

    def test_invalid_credentials_use_safe_unauthorized_response(self) -> None:
        self.service.login.side_effect = self.UnauthorizedError("Invalid email or password.")

        response = self.client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "password1"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["message"], "Invalid email or password.")

    def test_signup_unexpected_service_error_uses_safe_500_response(self) -> None:
        self.service.signup.side_effect = RuntimeError("database password failure")

        response = self.client.post(
            "/api/v1/auth/signup",
            json={"email": "user@example.com", "password": "password1"},
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "INTERNAL_SERVER_ERROR")
        self.assertEqual(response.json()["error"]["message"], "An unexpected error occurred.")

    def test_unexpected_service_error_uses_safe_500_response(self) -> None:
        self.service.login.side_effect = RuntimeError("database password failure")

        response = self.client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "password1"},
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "INTERNAL_SERVER_ERROR")
        self.assertEqual(response.json()["error"]["message"], "An unexpected error occurred.")


if __name__ == "__main__":
    unittest.main()
