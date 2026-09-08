"""Unit tests for authenticated user self-service use cases."""

from __future__ import annotations

import asyncio
import importlib
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

BACKEND_ROOT = Path(__file__).resolve().parents[1]
GATEWAY_ROOT = BACKEND_ROOT / "gateway-service"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _load_user_service_module():
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]
    while str(GATEWAY_ROOT) in sys.path:
        sys.path.remove(str(GATEWAY_ROOT))
    sys.path.insert(0, str(GATEWAY_ROOT))
    return importlib.import_module("app.services.user_service")


class _DuplicateEmailError:
    constraint_name = "uq_users_email"


class UserServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_user_service_module()
        self.session = MagicMock(spec=AsyncSession)
        self.session.commit = AsyncMock()
        self.repository = MagicMock()
        self.repository.get_by_email = AsyncMock()
        self.repository.update = AsyncMock()
        self.service = self.module.UserService(self.session, self.repository)

        from shared.database.models.user import User
        from shared.exceptions.common import ConflictError
        from shared.schemas.user import UserUpdate

        self.User = User
        self.ConflictError = ConflictError
        self.UserUpdate = UserUpdate

    def _user(self, email: str = "owner@example.com") -> object:
        now = datetime.now(timezone.utc)
        return self.User(
            id=uuid.uuid4(),
            email=email,
            password_hash="persisted-hash",
            created_at=now,
            updated_at=now,
        )

    def test_get_current_user_returns_safe_dto_without_query_or_commit(self) -> None:
        user = self._user()

        result = asyncio.run(self.service.get_current_user(user))

        self.assertEqual(result.id, str(user.id))
        self.assertEqual(result.email, user.email)
        self.assertNotIn("password_hash", result.model_dump())
        self.repository.get_by_email.assert_not_called()
        self.session.commit.assert_not_called()

    def test_update_normalizes_email_targets_authenticated_user_and_commits_once(self) -> None:
        user = self._user()
        self.repository.get_by_email.return_value = None
        self.repository.update.return_value = user

        result = asyncio.run(
            self.service.update_current_user(user, self.UserUpdate(email="  NEW@Example.COM "))
        )

        self.assertEqual(user.email, "new@example.com")
        self.repository.get_by_email.assert_awaited_once_with("new@example.com")
        self.repository.update.assert_awaited_once_with(user)
        self.session.commit.assert_awaited_once()
        self.session.rollback.assert_not_called()
        self.assertEqual(result.id, str(user.id))
        self.assertEqual(result.email, "new@example.com")

    def test_duplicate_email_raises_conflict_without_update_or_commit(self) -> None:
        user = self._user()
        self.repository.get_by_email.return_value = self._user("other@example.com")

        with self.assertRaisesRegex(self.ConflictError, "Email is already registered"):
            asyncio.run(
                self.service.update_current_user(user, self.UserUpdate(email="other@example.com"))
            )

        self.repository.update.assert_not_called()
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()

    def test_duplicate_email_race_raises_conflict_without_commit(self) -> None:
        user = self._user()
        self.repository.get_by_email.return_value = None
        self.repository.update.side_effect = IntegrityError(
            "update users", {}, _DuplicateEmailError()
        )

        with self.assertRaisesRegex(self.ConflictError, "Email is already registered"):
            asyncio.run(
                self.service.update_current_user(user, self.UserUpdate(email="other@example.com"))
            )

        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()

    def test_unexpected_persistence_error_propagates_without_commit(self) -> None:
        user = self._user()
        self.repository.get_by_email.return_value = None
        self.repository.update.side_effect = RuntimeError("database unavailable")

        with self.assertRaisesRegex(RuntimeError, "database unavailable"):
            asyncio.run(
                self.service.update_current_user(user, self.UserUpdate(email="new@example.com"))
            )

        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()

    def test_unchanged_canonical_email_does_not_write_or_commit(self) -> None:
        user = self._user("owner@example.com")

        result = asyncio.run(
            self.service.update_current_user(user, self.UserUpdate(email=" OWNER@example.com "))
        )

        self.assertEqual(result.email, "owner@example.com")
        self.repository.get_by_email.assert_not_called()
        self.repository.update.assert_not_called()
        self.session.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
