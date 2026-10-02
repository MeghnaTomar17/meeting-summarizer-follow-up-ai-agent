"""Phase 2.5 PostgreSQL database foundation tests."""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_ROOT = BACKEND_ROOT / "migrations"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


class DatabaseFoundationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        from shared.config.base import get_base_settings

        get_base_settings.cache_clear()

    def tearDown(self) -> None:
        from shared.config.base import get_base_settings
        from shared.database import engine as engine_module
        from shared.database import session as session_module

        get_base_settings.cache_clear()
        engine_module._engine = None
        session_module._session_factory = None

    def test_declarative_base_available(self) -> None:
        from shared.database.base import Base

        self.assertTrue(hasattr(Base, "metadata"))
        self.assertIsNotNone(Base.metadata)

    def test_uuid_mixin_fields(self) -> None:
        from shared.database.mixins import UUIDPrimaryKeyMixin

        self.assertIn("id", UUIDPrimaryKeyMixin.__annotations__)

    def test_timestamp_mixin_fields(self) -> None:
        from shared.database.mixins import TimestampMixin

        self.assertIn("created_at", TimestampMixin.__annotations__)
        self.assertIn("updated_at", TimestampMixin.__annotations__)

    def test_database_settings_defaults(self) -> None:
        from shared.config.base import SharedSettings

        settings = SharedSettings()
        self.assertTrue(settings.database_url.startswith("postgresql+asyncpg://"))
        self.assertEqual(settings.database_pool_size, 10)
        self.assertEqual(settings.database_max_overflow, 10)
        self.assertEqual(settings.database_pool_timeout, 30)
        self.assertEqual(settings.database_pool_recycle, 1800)
        self.assertFalse(settings.database_echo)

    def test_database_pool_settings_validation(self) -> None:
        from shared.config.base import SharedSettings

        with self.assertRaises(ValidationError):
            SharedSettings(database_pool_size=0)

    @patch("shared.database.engine.create_async_engine")
    def test_engine_construction_uses_settings(self, mock_create_engine: MagicMock) -> None:
        from shared.database.engine import create_database_engine, get_engine

        mock_create_engine.return_value = MagicMock(name="engine")

        engine = create_database_engine(
            "postgresql+asyncpg://user:pass@localhost:5432/test_db",
            pool_size=5,
            max_overflow=2,
            pool_timeout=15,
            pool_recycle=900,
            echo=True,
        )

        self.assertIs(engine, get_engine())
        mock_create_engine.assert_called_once_with(
            "postgresql+asyncpg://user:pass@localhost:5432/test_db",
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=2,
            pool_timeout=15,
            pool_recycle=900,
            echo=True,
        )

    @patch("shared.database.engine.create_async_engine")
    def test_session_factory_and_lifecycle(self, mock_create_engine: MagicMock) -> None:
        from shared.database.engine import get_engine
        from shared.database.session import (
            close_database,
            configure_session_factory,
            get_db_session,
            get_session_factory,
            init_database,
        )

        mock_engine = MagicMock(name="engine")
        mock_create_engine.return_value = mock_engine

        async def run() -> None:
            await init_database(
                "postgresql+asyncpg://user:pass@localhost:5432/test_db",
                pool_size=5,
                max_overflow=2,
                pool_timeout=15,
                pool_recycle=900,
                echo=False,
            )
            self.assertIsNotNone(get_session_factory())
            self.assertIs(get_engine(), mock_engine)

            mock_engine.dispose = AsyncMock()
            await close_database()
            self.assertIsNone(get_session_factory())

        asyncio.run(run())

        async def run_dependency_without_factory() -> None:
            gen = get_db_session()
            with self.assertRaises(RuntimeError):
                await gen.__anext__()

        asyncio.run(run_dependency_without_factory())

    @patch("shared.database.engine.create_async_engine")
    def test_db_session_rolls_back_on_exception(self, mock_create_engine: MagicMock) -> None:
        from shared.database.session import configure_session_factory, get_db_session

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_factory = MagicMock(return_value=mock_session)
        configure_session_factory(mock_create_engine.return_value)
        from shared.database import session as session_module

        session_module._session_factory = mock_factory

        async def run() -> None:
            gen = get_db_session()
            await gen.__anext__()
            with self.assertRaises(ValueError):
                await gen.athrow(ValueError("boom"))
            mock_session.rollback.assert_awaited_once()

        asyncio.run(run())

    def test_postgres_connectivity_without_engine(self) -> None:
        from shared.database.health import check_postgres_connectivity

        async def run() -> bool:
            return await check_postgres_connectivity(engine=None)

        self.assertFalse(asyncio.run(run()))

    def test_postgres_connectivity_success(self) -> None:
        from shared.database.health import check_postgres_connectivity

        mock_engine = MagicMock()
        mock_connection = AsyncMock()
        mock_connection.execute = AsyncMock()
        mock_connection.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_connection.__aexit__ = AsyncMock(return_value=None)
        mock_engine.connect.return_value = mock_connection

        async def run() -> bool:
            return await check_postgres_connectivity(engine=mock_engine)

        self.assertTrue(asyncio.run(run()))

    def test_postgres_connectivity_failure_handling(self) -> None:
        from sqlalchemy.exc import SQLAlchemyError
        from shared.database.health import check_postgres_connectivity

        mock_engine = MagicMock()
        mock_connection = AsyncMock()
        mock_connection.__aenter__ = AsyncMock(side_effect=SQLAlchemyError("connection failed"))
        mock_engine.connect.return_value = mock_connection

        async def run() -> bool:
            return await check_postgres_connectivity(engine=mock_engine)

        self.assertFalse(asyncio.run(run()))

    def test_postgres_connectivity_oserror_failure(self) -> None:
        from shared.database.health import check_postgres_connectivity

        mock_engine = MagicMock()
        mock_engine.connect.side_effect = OSError(10061, "connection refused")

        async def run() -> bool:
            return await check_postgres_connectivity(engine=mock_engine)

        self.assertFalse(asyncio.run(run()))

    def test_alembic_ini_configured(self) -> None:
        repo_root = BACKEND_ROOT.parent
        alembic_ini = repo_root / "alembic.ini"
        self.assertTrue(alembic_ini.is_file())
        content = alembic_ini.read_text(encoding="utf-8")
        self.assertIn("script_location = backend/migrations", content)

    def test_alembic_env_target_metadata(self) -> None:
        env_source = (MIGRATIONS_ROOT / "env.py").read_text(encoding="utf-8")
        self.assertIn("target_metadata = Base.metadata", env_source)
        self.assertIn("import shared.database.models", env_source)

    def test_alembic_env_uses_settings_database_url(self) -> None:
        env_source = (MIGRATIONS_ROOT / "env.py").read_text(encoding="utf-8")
        self.assertIn("get_base_settings().database_url", env_source)

    def test_persisted_models_register_expected_metadata(self) -> None:
        import shared.database.models  # noqa: F401
        from shared.database.base import Base
        from shared.database.models.meeting import Meeting

        self.assertEqual(
            set(Base.metadata.tables),
            {
                "meetings",
                "transcripts",
                "users",
                "refresh_sessions",
                "summaries",
                "tasks",
                "decisions",
                "followups",
                "meeting_insights",
            },
        )
        self.assertEqual(Meeting.__table__.c.status.type.enums, [
            "pending",
            "processing",
            "ready",
            "failed",
        ])

    def test_initial_meeting_schema_revision_exists(self) -> None:
        revision_path = (
            MIGRATIONS_ROOT
            / "versions"
            / "0001_create_meetings_and_transcripts.py"
        )
        source = revision_path.read_text(encoding="utf-8")

        self.assertTrue(revision_path.is_file())
        self.assertIn('revision: str = "0001_meetings_transcripts"', source)
        self.assertIn('op.create_table(\n        "meetings"', source)
        self.assertIn('op.create_table(\n        "transcripts"', source)
        self.assertIn('ondelete="CASCADE"', source)


MEETING_ROOT = BACKEND_ROOT / "meeting-service"


class MeetingReadinessTestCase(unittest.TestCase):
    def setUp(self) -> None:
        from shared.config.base import AppEnv
        from shared.utils.logger import configure_logging

        configure_logging(
            service_name="meeting-service",
            log_level="INFO",
            app_env=AppEnv.DEVELOPMENT,
        )

        for key in list(sys.modules):
            if key == "app" or key.startswith("app."):
                del sys.modules[key]
        if str(MEETING_ROOT) in sys.path:
            sys.path.remove(str(MEETING_ROOT))
        sys.path.insert(0, str(MEETING_ROOT))

    @patch("app.main.check_postgres_connectivity", new_callable=AsyncMock)
    def test_health_ready_returns_503_when_postgres_unavailable(
        self,
        mock_check: AsyncMock,
    ) -> None:
        import importlib

        from fastapi.testclient import TestClient

        mock_check.return_value = False
        main_module = importlib.import_module("app.main")

        with TestClient(main_module.app) as client:
            response = client.get(
                "/health/ready",
                headers={"X-Request-ID": "ready-unavailable"},
            )

        body = response.json()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(body["error"]["code"], "SERVICE_UNAVAILABLE")
        self.assertEqual(body["error"]["message"], "Required dependencies are unavailable.")
        self.assertEqual(body["error"]["request_id"], "ready-unavailable")
        self.assertEqual(response.headers["X-Request-ID"], "ready-unavailable")
        serialized = str(body)
        self.assertNotIn("10061", serialized)
        self.assertNotIn("OSError", serialized)
        self.assertNotIn("connection refused", serialized.lower())


@unittest.skipUnless(
    os.environ.get("RUN_POSTGRES_INTEGRATION") == "1",
    "Set RUN_POSTGRES_INTEGRATION=1 to run PostgreSQL integration tests",
)
class PostgresIntegrationTestCase(unittest.TestCase):
    def tearDown(self) -> None:
        from shared.database import engine as engine_module
        from shared.database import session as session_module

        async def cleanup() -> None:
            from shared.database.session import close_database

            await close_database()

        asyncio.run(cleanup())
        engine_module._engine = None
        session_module._session_factory = None

    def test_postgres_select_one(self) -> None:
        from shared.config.base import get_base_settings
        from shared.database.health import check_postgres_connectivity
        from shared.database.session import init_database

        settings = get_base_settings()

        async def run() -> bool:
            await init_database(
                settings.database_url,
                pool_size=settings.database_pool_size,
                max_overflow=settings.database_max_overflow,
                pool_timeout=settings.database_pool_timeout,
                pool_recycle=settings.database_pool_recycle,
                echo=False,
            )
            return await check_postgres_connectivity()

        self.assertTrue(asyncio.run(run()))


if __name__ == "__main__":
    unittest.main()
