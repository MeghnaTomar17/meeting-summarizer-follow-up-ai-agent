"""Unit tests for gateway signup and login use cases."""

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

from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

BACKEND_ROOT = Path(__file__).resolve().parents[1]
GATEWAY_ROOT = BACKEND_ROOT / "gateway-service"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _load_authentication_modules():
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]
    while str(GATEWAY_ROOT) in sys.path:
        sys.path.remove(str(GATEWAY_ROOT))
    sys.path.insert(0, str(GATEWAY_ROOT))
    return importlib.import_module("app.services.authentication_service")


class _DuplicateEmailError:
    constraint_name = "uq_users_email"


class AuthenticationServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_authentication_modules()
        self.session = MagicMock(spec=AsyncSession)
        self.session.commit = AsyncMock()
        self.repository = MagicMock()
        self.repository.get_by_email = AsyncMock()
        self.repository.create = AsyncMock()
        self.refresh_repository = MagicMock()
        self.refresh_repository.create = AsyncMock()
        self.refresh_repository.update = AsyncMock()
        self.refresh_repository.get_by_hash_for_update = AsyncMock()
        self.settings = SimpleNamespace(
            jwt_secret=SecretStr("test-secret-for-authentication-service"),
            jwt_algorithm="HS256",
            jwt_expire_minutes=60,
            refresh_token_expire_seconds=3600,
        )
        self.service = self.module.AuthenticationService(
            self.session,
            self.repository,
            self.settings,
            self.refresh_repository,
        )

        from app.schemas.auth import LoginRequest
        from shared.database.models.user import User
        from shared.exceptions.common import ConflictError, UnauthorizedError
        from shared.schemas.user import UserCreate

        self.LoginRequest = LoginRequest
        self.User = User
        self.UserCreate = UserCreate
        self.ConflictError = ConflictError
        self.UnauthorizedError = UnauthorizedError

    def _user(self, *, email: str = "user@example.com") -> object:
        now = datetime.now(timezone.utc)
        return self.User(
            id=uuid.uuid4(),
            email=email,
            password_hash="persisted-hash",
            created_at=now,
            updated_at=now,
        )

    def test_signup_normalizes_email_hashes_password_and_commits_once(self) -> None:
        created = self._user()
        self.repository.get_by_email.return_value = None
        self.repository.create.return_value = created
        payload = self.UserCreate(email="  USER@Example.COM ", password="password1")

        with patch.object(self.module, "hash_password", return_value="new-hash") as hash_password:
            result = asyncio.run(self.service.signup(payload))

        self.repository.get_by_email.assert_awaited_once_with("user@example.com")
        hash_password.assert_called_once_with("password1")
        persisted = self.repository.create.await_args.args[0]
        self.assertEqual(persisted.email, "user@example.com")
        self.assertEqual(persisted.password_hash, "new-hash")
        self.assertNotIn("password", persisted.__table__.c)
        self.session.commit.assert_awaited_once()
        self.session.rollback.assert_not_called()
        self.assertEqual(result.email, "user@example.com")
        self.assertNotIn("password_hash", result.model_dump())

    def test_duplicate_signup_raises_conflict_without_hashing_or_commit(self) -> None:
        self.repository.get_by_email.return_value = self._user()
        payload = self.UserCreate(email="user@example.com", password="password1")

        with patch.object(self.module, "hash_password") as hash_password:
            with self.assertRaisesRegex(self.ConflictError, "Email is already registered"):
                asyncio.run(self.service.signup(payload))

        hash_password.assert_not_called()
        self.repository.create.assert_not_called()
        self.session.commit.assert_not_called()

    def test_unique_constraint_race_raises_conflict_without_commit(self) -> None:
        self.repository.get_by_email.return_value = None
        self.repository.create.side_effect = IntegrityError(
            "insert users",
            {},
            _DuplicateEmailError(),
        )
        payload = self.UserCreate(email="user@example.com", password="password1")

        with patch.object(self.module, "hash_password", return_value="new-hash"):
            with self.assertRaisesRegex(self.ConflictError, "Email is already registered"):
                asyncio.run(self.service.signup(payload))

        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()

    def test_unexpected_signup_persistence_error_propagates_without_commit(self) -> None:
        self.repository.get_by_email.return_value = None
        self.repository.create.side_effect = RuntimeError("database unavailable")
        payload = self.UserCreate(email="user@example.com", password="password1")

        with patch.object(self.module, "hash_password", return_value="new-hash"):
            with self.assertRaisesRegex(RuntimeError, "database unavailable"):
                asyncio.run(self.service.signup(payload))

        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()

    def test_login_normalizes_email_verifies_password_and_issues_token(self) -> None:
        user = self._user(email="user@example.com")
        self.repository.get_by_email.return_value = user
        payload = self.LoginRequest(email=" USER@Example.COM ", password="password1")

        with (
            patch.object(self.module, "verify_password", return_value=True) as verify_password,
            patch.object(self.module, "create_access_token", return_value="signed-token") as create_token,
        ):
            result = asyncio.run(self.service.login(payload))

        self.repository.get_by_email.assert_awaited_once_with("user@example.com")
        verify_password.assert_called_once_with("password1", "persisted-hash")
        create_token.assert_called_once_with(
            str(user.id),
            secret="test-secret-for-authentication-service",
            algorithm="HS256",
            expires_minutes=60,
        )
        self.assertEqual(result.access_token, "signed-token")
        self.assertTrue(result.refresh_token)
        self.assertNotEqual(result.refresh_token, "signed-token")
        self.assertEqual(result.token_type, "bearer")
        self.session.commit.assert_awaited_once()
        saved_session = self.refresh_repository.create.await_args.args[0]
        self.assertEqual(saved_session.user_id, user.id)
        self.assertEqual(saved_session.token_hash, self.module.AuthenticationService._hash_refresh_token(result.refresh_token))
        self.assertNotEqual(saved_session.token_hash, result.refresh_token)

    def test_refresh_rotates_token_and_revokes_previous_session(self) -> None:
        user = self._user()
        session = self.module.RefreshSession(
            user_id=user.id,
            token_hash=self.module.AuthenticationService._hash_refresh_token("old-token"),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        self.refresh_repository.get_by_hash_for_update.return_value = session
        self.repository.get_by_id = AsyncMock(return_value=user)
        payload = self.module.RefreshRequest(refresh_token="old-token")
        with patch.object(self.module, "create_access_token", return_value="fresh-access"):
            result = asyncio.run(self.service.refresh(payload))
        self.assertEqual(result.access_token, "fresh-access")
        self.assertNotEqual(result.refresh_token, "old-token")
        self.assertIsNotNone(session.revoked_at)
        self.refresh_repository.update.assert_awaited_once_with(session)
        replacement = self.refresh_repository.create.await_args.args[0]
        self.assertEqual(replacement.user_id, user.id)
        self.assertEqual(self.session.commit.await_count, 1)

    def test_refresh_rejects_expired_session_generically(self) -> None:
        session = self.module.RefreshSession(
            user_id=uuid.uuid4(), token_hash="0" * 64,
            expires_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
        )
        self.refresh_repository.get_by_hash_for_update.return_value = session
        with self.assertRaises(self.UnauthorizedError) as error:
            asyncio.run(self.service.refresh(self.module.RefreshRequest(refresh_token="expired")))
        self.assertEqual(error.exception.message, "Invalid refresh token.")
        self.repository.get_by_id.assert_not_called()
        self.session.commit.assert_not_called()

    def test_logout_is_idempotent_and_commits(self) -> None:
        self.refresh_repository.get_by_hash_for_update.return_value = None
        result = asyncio.run(self.service.logout(self.module.RefreshRequest(refresh_token="unknown")))
        self.assertTrue(result.success)
        self.session.commit.assert_awaited_once()

    def test_unknown_user_and_incorrect_password_share_safe_error(self) -> None:
        payload = self.LoginRequest(email="user@example.com", password="password1")
        self.repository.get_by_email.return_value = None

        with self.assertRaises(self.UnauthorizedError) as missing_error:
            asyncio.run(self.service.login(payload))

        self.repository.get_by_email.return_value = self._user()
        with patch.object(self.module, "verify_password", return_value=False):
            with self.assertRaises(self.UnauthorizedError) as bad_password_error:
                asyncio.run(self.service.login(payload))

        self.assertEqual(missing_error.exception.message, "Invalid email or password.")
        self.assertEqual(bad_password_error.exception.message, "Invalid email or password.")
        self.session.commit.assert_not_called()

    def test_malformed_password_hash_uses_safe_invalid_credentials_error(self) -> None:
        user = self._user()
        user.password_hash = "not-a-valid-hash"
        self.repository.get_by_email.return_value = user
        payload = self.LoginRequest(email="user@example.com", password="password1")

        with patch.object(self.module, "create_access_token") as create_token:
            with self.assertRaises(self.UnauthorizedError) as error:
                asyncio.run(self.service.login(payload))

        self.assertEqual(error.exception.http_status, 401)
        self.assertEqual(error.exception.message, "Invalid email or password.")
        create_token.assert_not_called()
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()

    def test_password_hashing_and_jwt_helpers_preserve_secret_boundaries(self) -> None:
        passwords = importlib.import_module("app.auth.passwords")
        jwt_module = importlib.import_module("app.auth.jwt")
        password_hash = passwords.hash_password("password1")

        self.assertNotEqual(password_hash, "password1")
        self.assertTrue(passwords.verify_password("password1", password_hash))
        self.assertFalse(passwords.verify_password("wrong-password", password_hash))

        token = jwt_module.create_access_token(
            "user-id",
            secret="test-secret-for-jwt",
            algorithm="HS256",
            expires_minutes=60,
        )
        claims = jwt_module.decode_access_token(
            token,
            secret="test-secret-for-jwt",
            algorithm="HS256",
        )
        self.assertEqual(claims["sub"], "user-id")
        self.assertEqual(claims["type"], "access")
        self.assertIn("iat", claims)
        self.assertIn("exp", claims)
        self.assertNotIn("password", claims)
        self.assertNotIn("password_hash", claims)

    def test_gateway_database_lifecycle_delegates_to_shared_infrastructure(self) -> None:
        database_module = importlib.import_module("app.database")
        settings = SimpleNamespace(
            database_url="postgresql+asyncpg://user:pass@localhost:5432/test_db",
            database_pool_size=5,
            database_max_overflow=2,
            database_pool_timeout=30,
            database_pool_recycle=1800,
            database_echo=False,
        )

        with (
            patch.object(database_module, "init_database", new_callable=AsyncMock) as init_database,
            patch.object(database_module, "close_database", new_callable=AsyncMock) as close_database,
        ):
            asyncio.run(database_module.startup_database(settings))
            asyncio.run(database_module.shutdown_database())

        init_database.assert_awaited_once_with(
            settings.database_url,
            pool_size=5,
            max_overflow=2,
            pool_timeout=30,
            pool_recycle=1800,
            echo=False,
        )
        close_database.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
