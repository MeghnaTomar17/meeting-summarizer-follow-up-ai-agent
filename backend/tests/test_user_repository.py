"""Unit tests for the gateway authentication user repository."""

from __future__ import annotations

import asyncio
import importlib
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

BACKEND_ROOT = Path(__file__).resolve().parents[1]
GATEWAY_ROOT = BACKEND_ROOT / "gateway-service"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _load_user_repository():
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]
    while str(GATEWAY_ROOT) in sys.path:
        sys.path.remove(str(GATEWAY_ROOT))
    sys.path.insert(0, str(GATEWAY_ROOT))

    module = importlib.import_module("app.repositories.user_repository")
    return module.UserRepository


class UserRepositoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.UserRepository = _load_user_repository()
        self.session = MagicMock(spec=AsyncSession)
        self.session.flush = AsyncMock()
        self.session.execute = AsyncMock()

        from shared.database.models.user import User

        self.User = User

    def _user(self) -> object:
        return self.User(
            id=uuid.uuid4(),
            email="user@example.com",
            password_hash="$not-a-real-password-hash",
        )

    def test_user_model_has_only_required_authentication_fields(self) -> None:
        columns = self.User.__table__.c

        self.assertEqual(self.User.__tablename__, "users")
        self.assertFalse(columns.email.nullable)
        self.assertFalse(columns.password_hash.nullable)
        self.assertNotIn("password", columns)
        self.assertIn("uq_users_email", {constraint.name for constraint in self.User.__table__.constraints})

    def test_create_adds_and_flushes_without_transaction_control(self) -> None:
        user = self._user()
        repository = self.UserRepository(self.session)

        result = asyncio.run(repository.create(user))

        self.assertIs(result, user)
        self.session.add.assert_called_once_with(user)
        self.session.flush.assert_awaited_once()
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()

    def test_get_by_id_returns_entity_or_none_without_transaction_control(self) -> None:
        user = self._user()
        repository = self.UserRepository(self.session)
        result = MagicMock()
        result.scalar_one_or_none.return_value = user
        self.session.execute.return_value = result

        found = asyncio.run(repository.get_by_id(user.id))
        self.assertIs(found, user)

        statement = self.session.execute.await_args.args[0]
        self.assertIn("WHERE users.id", str(statement))
        self.assertIn(user.id, statement.compile().params.values())

        result.scalar_one_or_none.return_value = None
        missing = asyncio.run(repository.get_by_id(uuid.uuid4()))
        self.assertIsNone(missing)
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()

    def test_get_by_email_returns_entity_or_none_without_transaction_control(self) -> None:
        user = self._user()
        repository = self.UserRepository(self.session)
        result = MagicMock()
        result.scalar_one_or_none.return_value = user
        self.session.execute.return_value = result

        found = asyncio.run(repository.get_by_email(user.email))
        self.assertIs(found, user)

        statement = self.session.execute.await_args.args[0]
        self.assertIn("WHERE users.email", str(statement))
        self.assertIn(user.email, statement.compile().params.values())

        result.scalar_one_or_none.return_value = None
        missing = asyncio.run(repository.get_by_email("missing@example.com"))
        self.assertIsNone(missing)
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()

    def test_update_flushes_without_transaction_control(self) -> None:
        user = self._user()
        repository = self.UserRepository(self.session)

        result = asyncio.run(repository.update(user))

        self.assertIs(result, user)
        self.session.add.assert_called_once_with(user)
        self.session.flush.assert_awaited_once()
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
