"""Unit tests for Gateway current-user authentication dependency."""

from __future__ import annotations

import asyncio
import importlib
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

BACKEND_ROOT = Path(__file__).resolve().parents[1]
GATEWAY_ROOT = BACKEND_ROOT / "gateway-service"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

_SECRET = "test-secret-for-current-user-dependency"
_ALGORITHM = "HS256"


def _load_dependencies_module():
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]
    while str(GATEWAY_ROOT) in sys.path:
        sys.path.remove(str(GATEWAY_ROOT))
    sys.path.insert(0, str(GATEWAY_ROOT))
    return importlib.import_module("app.auth.dependencies")


class CurrentUserDependencyTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_dependencies_module()
        self.session = MagicMock(spec=AsyncSession)
        self.settings = SimpleNamespace(
            jwt_secret=SecretStr(_SECRET),
            jwt_algorithm=_ALGORITHM,
        )

        from shared.database.models.user import User
        from shared.exceptions.common import UnauthorizedError

        self.User = User
        self.UnauthorizedError = UnauthorizedError

    def _credentials(self, token: str, scheme: str = "Bearer") -> HTTPAuthorizationCredentials:
        return HTTPAuthorizationCredentials(scheme=scheme, credentials=token)

    def _token(self, subject: str, *, token_type: str = "access", expires_in: int = 60) -> str:
        now = datetime.now(timezone.utc)
        return jwt.encode(
            {
                "sub": subject,
                "type": token_type,
                "iat": now,
                "exp": now + timedelta(minutes=expires_in),
            },
            _SECRET,
            algorithm=_ALGORITHM,
        )

    def _user(self, user_id: uuid.UUID) -> object:
        now = datetime.now(timezone.utc)
        return self.User(
            id=user_id,
            email="user@example.com",
            password_hash="persisted-hash",
            created_at=now,
            updated_at=now,
        )

    def _run_with_repository(
        self,
        credentials: HTTPAuthorizationCredentials | None,
        user: object | None,
    ) -> tuple[object, MagicMock]:
        repository = MagicMock()
        repository.get_by_id = AsyncMock(return_value=user)
        with (
            patch.object(self.module, "get_settings", return_value=self.settings),
            patch.object(self.module, "UserRepository", return_value=repository),
        ):
            result = asyncio.run(self.module.get_current_user(credentials, self.session))
        return result, repository

    def test_valid_access_token_returns_existing_user_without_transaction_control(self) -> None:
        user_id = uuid.uuid4()
        user = self._user(user_id)

        result, repository = self._run_with_repository(
            self._credentials(self._token(str(user_id))),
            user,
        )

        self.assertIs(result, user)
        repository.get_by_id.assert_awaited_once_with(user_id)
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()
        self.assertFalse(hasattr(result, "password"))

    def test_missing_or_malformed_authorization_returns_unauthorized_without_lookup(self) -> None:
        for credentials in (None, self._credentials("token", scheme="Basic")):
            with patch.object(self.module, "UserRepository") as repository:
                with self.assertRaises(self.UnauthorizedError) as error:
                    asyncio.run(self.module.get_current_user(credentials, self.session))
            self.assertEqual(error.exception.http_status, 401)
            repository.assert_not_called()

    def test_invalid_signature_expired_wrong_type_and_invalid_subject_return_unauthorized(self) -> None:
        invalid_signature = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "type": "access",
                "exp": datetime.now(timezone.utc) + timedelta(minutes=60),
            },
            "different-secret",
            algorithm=_ALGORITHM,
        )
        tokens = (
            invalid_signature,
            self._token(str(uuid.uuid4()), expires_in=-1),
            self._token(str(uuid.uuid4()), token_type="refresh"),
            self._token("not-a-uuid"),
        )

        for token in tokens:
            with patch.object(self.module, "UserRepository") as repository:
                with self.assertRaises(self.UnauthorizedError) as error:
                    asyncio.run(self.module.get_current_user(self._credentials(token), self.session))
            self.assertEqual(error.exception.message, "Not authenticated.")
            repository.assert_not_called()

    def test_valid_token_for_missing_user_returns_unauthorized_without_transaction_control(self) -> None:
        user_id = uuid.uuid4()

        with self.assertRaises(self.UnauthorizedError) as error:
            self._run_with_repository(self._credentials(self._token(str(user_id))), None)

        self.assertEqual(error.exception.http_status, 401)
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
