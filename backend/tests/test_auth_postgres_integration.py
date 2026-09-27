"""Opt-in PostgreSQL integration tests for refresh-session lifecycle semantics."""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import delete, select

BACKEND_ROOT = Path(__file__).resolve().parents[1]
GATEWAY_ROOT = BACKEND_ROOT / "gateway-service"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(GATEWAY_ROOT) not in sys.path:
    sys.path.insert(0, str(GATEWAY_ROOT))


@unittest.skipUnless(
    os.environ.get("RUN_POSTGRES_INTEGRATION") == "1",
    "Set RUN_POSTGRES_INTEGRATION=1 to run PostgreSQL integration tests",
)
class RefreshSessionPostgresIntegrationTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        for key in list(sys.modules):
            if key == "app" or key.startswith("app."):
                del sys.modules[key]
        while str(GATEWAY_ROOT) in sys.path:
            sys.path.remove(str(GATEWAY_ROOT))
        sys.path.insert(0, str(GATEWAY_ROOT))
        from app.config.settings import GatewaySettings
        from shared.config.base import get_base_settings
        from shared.database.session import init_database, get_session_factory
        from app.services.authentication_service import AuthenticationService
        from app.repositories.user_repository import UserRepository
        from app.repositories.refresh_session_repository import RefreshSessionRepository
        from shared.schemas.user import UserCreate

        settings = get_base_settings()
        await init_database(
            settings.database_url,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_timeout=settings.database_pool_timeout,
            pool_recycle=settings.database_pool_recycle,
            echo=False,
        )
        self.session_factory = get_session_factory()
        self.settings = GatewaySettings()
        self.user_payload = UserCreate(
            email=f"refresh-{uuid.uuid4()}@example.com",
            password="integration-test-password",
        )
        async with self.session_factory() as session:
            self.service = AuthenticationService(
                session,
                UserRepository(session),
                self.settings,
                RefreshSessionRepository(session),
            )
            user = await self.service.signup(self.user_payload)
            self.user_id = uuid.UUID(user.id)

    async def asyncTearDown(self) -> None:
        from shared.database.session import close_database
        from shared.database.models.user import User

        try:
            async with self.session_factory() as session:
                await session.execute(delete(User).where(User.id == self.user_id))
                await session.commit()
        finally:
            await close_database()

    async def _login(self) -> str:
        from app.schemas.auth import LoginRequest

        async with self.session_factory() as session:
            service = self._service(session)
            pair = await service.login(
                LoginRequest(email=self.user_payload.email, password=self.user_payload.password)
            )
            return pair.refresh_token

    @staticmethod
    def _service(session):
        from app.config.settings import GatewaySettings
        from app.services.authentication_service import AuthenticationService
        from app.repositories.user_repository import UserRepository
        from app.repositories.refresh_session_repository import RefreshSessionRepository

        return AuthenticationService(
            session,
            UserRepository(session),
            GatewaySettings(),
            RefreshSessionRepository(session),
        )

    async def _refresh(self, token: str):
        from app.schemas.auth import RefreshRequest

        async with self.session_factory() as session:
            return await self._service(session).refresh(RefreshRequest(refresh_token=token))

    async def _session_for_token(self, token: str):
        from app.services.authentication_service import AuthenticationService
        from shared.database.models.refresh_session import RefreshSession

        token_hash = AuthenticationService._hash_refresh_token(token)
        async with self.session_factory() as session:
            result = await session.execute(
                select(RefreshSession).where(RefreshSession.token_hash == token_hash)
            )
            return result.scalar_one_or_none()

    async def test_login_persists_only_hash_for_correct_user_and_expiration(self) -> None:
        from app.schemas.auth import LoginRequest

        async with self.session_factory() as session:
            pair = await self._service(session).login(
                LoginRequest(email=self.user_payload.email, password=self.user_payload.password)
            )
        stored = await self._session_for_token(pair.refresh_token)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.user_id, self.user_id)
        self.assertNotEqual(stored.token_hash, pair.refresh_token)
        self.assertEqual(
            stored.token_hash,
            hashlib.sha256(pair.refresh_token.encode()).hexdigest(),
        )
        expected = self.settings.refresh_token_expire_seconds
        remaining = (stored.expires_at - datetime.now(timezone.utc)).total_seconds()
        self.assertGreater(remaining, expected - 10)
        self.assertLessEqual(remaining, expected)

    async def test_refresh_rotation_and_second_old_token_use(self) -> None:
        from shared.exceptions.common import UnauthorizedError

        token_a = await self._login()
        pair_b = await self._refresh(token_a)
        with self.assertRaises(UnauthorizedError):
            await self._refresh(token_a)
        pair_c = await self._refresh(pair_b.refresh_token)
        self.assertNotEqual(pair_b.refresh_token, token_a)
        self.assertNotEqual(pair_c.refresh_token, pair_b.refresh_token)

    async def test_valid_logout_revokes_session_and_refresh_fails(self) -> None:
        from app.schemas.auth import RefreshRequest
        from shared.exceptions.common import UnauthorizedError

        token = await self._login()
        async with self.session_factory() as session:
            result = await self._service(session).logout(RefreshRequest(refresh_token=token))
        self.assertTrue(result.success)
        async with self.session_factory() as session:
            repeated = await self._service(session).logout(RefreshRequest(refresh_token=token))
        self.assertTrue(repeated.success)
        stored = await self._session_for_token(token)
        self.assertIsNotNone(stored.revoked_at)
        with self.assertRaises(UnauthorizedError):
            await self._refresh(token)

    async def test_rotating_one_session_leaves_another_session_valid(self) -> None:
        token_a = await self._login()
        token_b = await self._login()
        pair_a = await self._refresh(token_a)
        pair_b = await self._refresh(token_b)
        self.assertNotEqual(pair_a.refresh_token, pair_b.refresh_token)

    async def test_concurrent_refresh_of_one_token_has_at_most_one_success(self) -> None:
        from app.schemas.auth import RefreshRequest
        from shared.exceptions.common import UnauthorizedError

        token = await self._login()

        async def attempt():
            async with self.session_factory() as session:
                return await self._service(session).refresh(RefreshRequest(refresh_token=token))

        outcomes = await asyncio.gather(attempt(), attempt(), return_exceptions=True)
        successes = [result for result in outcomes if not isinstance(result, BaseException)]
        failures = [result for result in outcomes if isinstance(result, BaseException)]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], UnauthorizedError)
        replacement = await self._refresh(successes[0].refresh_token)
        self.assertTrue(replacement.refresh_token)

    async def test_failed_replacement_flush_rolls_back_old_session_revocation(self) -> None:
        from app.schemas.auth import RefreshRequest
        from app.repositories.refresh_session_repository import RefreshSessionRepository
        from shared.database.models.refresh_session import RefreshSession

        token = await self._login()

        class FailingReplacementRepository(RefreshSessionRepository):
            async def create(self, refresh_session: RefreshSession) -> RefreshSession:
                raise RuntimeError("injected replacement persistence failure")

        async with self.session_factory() as session:
            service = self._service(session)
            service._refresh_sessions = FailingReplacementRepository(session)
            with self.assertRaisesRegex(RuntimeError, "injected replacement"):
                await service.refresh(RefreshRequest(refresh_token=token))
            await session.rollback()

        stored = await self._session_for_token(token)
        self.assertIsNone(stored.revoked_at)
        pair = await self._refresh(token)
        self.assertTrue(pair.refresh_token)


if __name__ == "__main__":
    unittest.main()
