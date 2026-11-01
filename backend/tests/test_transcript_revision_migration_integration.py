"""Opt-in migration verification for an empty disposable PostgreSQL database."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

REPOSITORY_ROOT = Path(__file__).resolve().parents[1].parent
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _validated_test_url(configured: str | None, normal: str | None) -> tuple[str, str]:
    if not configured:
        raise ValueError("TRANSCRIPT_REVISION_MIGRATION_TEST_DATABASE_URL is required; no fallback is permitted.")
    try:
        parsed = make_url(configured)
    except Exception as error:
        raise ValueError("The transcript migration test URL is invalid.") from error
    database_name = parsed.database or ""
    if parsed.get_backend_name() != "postgresql":
        raise ValueError("The transcript migration test URL must use PostgreSQL.")
    if not database_name.endswith("_disposable_test"):
        raise ValueError("The transcript migration test database must end in _disposable_test.")
    if normal:
        try:
            normal_database = make_url(normal).database
        except Exception:
            normal_database = None
        if normal_database == database_name:
            raise ValueError("The transcript migration database must differ from DATABASE_URL.")
    return configured, database_name


class TranscriptRevisionMigrationSafetyTestCase(unittest.TestCase):
    def test_requires_explicit_disposable_database_without_fallback(self) -> None:
        with self.assertRaisesRegex(ValueError, "no fallback"):
            _validated_test_url(None, "postgresql://host/ordinary")
        with self.assertRaisesRegex(ValueError, "end in _disposable_test"):
            _validated_test_url("postgresql://host/ordinary", None)


@unittest.skipUnless(
    os.environ.get("RUN_TRANSCRIPT_REVISION_MIGRATION_INTEGRATION") == "1",
    "Set RUN_TRANSCRIPT_REVISION_MIGRATION_INTEGRATION=1 for disposable PostgreSQL verification.",
)
class TranscriptRevisionMigrationIntegrationTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        try:
            self.database_url, database_name = _validated_test_url(
                os.environ.get("TRANSCRIPT_REVISION_MIGRATION_TEST_DATABASE_URL"),
                os.environ.get("DATABASE_URL"),
            )
        except ValueError as error:
            self.fail(str(error))
        self.engine = create_async_engine(self.database_url)
        self.migration_started = False
        try:
            async with self.engine.connect() as connection:
                actual_name = await connection.scalar(text("SELECT current_database()"))
                table_names = await connection.run_sync(
                    lambda sync_connection: inspect(sync_connection).get_table_names()
                )
            if actual_name != database_name:
                self.fail("Connected database does not match the validated disposable name.")
            if table_names:
                self.fail("Disposable migration database must be empty before the test.")

            self._alembic("upgrade", "0006_processing_jobs")
            self.migration_started = True
            self.user_id = uuid.uuid4()
            self.meeting_id = uuid.uuid4()
            self.transcript_id = uuid.uuid4()
            self.organization_id = uuid.uuid4()
            async with self.engine.begin() as connection:
                await connection.execute(
                    text("INSERT INTO users (id, email, password_hash) VALUES (:id, :email, 'migration-test-hash')"),
                    {"id": self.user_id, "email": f"revision-{self.user_id}@example.test"},
                )
                await connection.execute(
                    text(
                        "INSERT INTO meetings (id, organization_id, created_by, title, participants, status) "
                        "VALUES (:id, :org, :owner, 'Revision test', '[]'::jsonb, 'pending')"
                    ),
                    {"id": self.meeting_id, "org": self.organization_id, "owner": self.user_id},
                )
                await connection.execute(
                    text(
                        "INSERT INTO transcripts (id, meeting_id, segments, language) "
                        "VALUES (:id, :meeting, '[{\"index\": 0, \"text\": \"original\"}]'::jsonb, 'en')"
                    ),
                    {"id": self.transcript_id, "meeting": self.meeting_id},
                )
            self._alembic("upgrade", "head")
        except BaseException:
            if self.migration_started:
                self._try_alembic("downgrade", "base")
            await self.engine.dispose()
            raise

    async def asyncTearDown(self) -> None:
        try:
            if self.migration_started:
                self._alembic("downgrade", "base")
        finally:
            await self.engine.dispose()

    def _try_alembic(self, direction: str, revision: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["DATABASE_URL"] = self.database_url
        return subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", direction, revision],
            cwd=REPOSITORY_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def _alembic(self, direction: str, revision: str) -> None:
        result = self._try_alembic(direction, revision)
        if result.returncode != 0:
            self.fail(f"Alembic {direction} {revision} failed; database URL and output are suppressed.")

    async def test_backfill_constraints_and_lossless_downgrade_reupgrade(self) -> None:
        async with self.engine.begin() as connection:
            existing = await connection.execute(
                text("SELECT id, revision_number, segments FROM transcripts WHERE id = :id"),
                {"id": self.transcript_id},
            )
            row = existing.one()
            self.assertEqual(row.revision_number, 1)
            self.assertEqual(row.segments[0]["text"], "original")

            await connection.execute(
                text(
                    "INSERT INTO transcripts (id, meeting_id, revision_number, segments, language) "
                    "VALUES (:id, :meeting, 2, '[]'::jsonb, 'en')"
                ),
                {"id": uuid.uuid4(), "meeting": self.meeting_id},
            )
            with self.assertRaises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            "INSERT INTO transcripts (id, meeting_id, revision_number, segments, language) "
                            "VALUES (:id, :meeting, 2, '[]'::jsonb, 'en')"
                        ),
                        {"id": uuid.uuid4(), "meeting": self.meeting_id},
                    )

        # Downgrade must fail closed while a meeting has multiple revisions.
        self.assertNotEqual(self._try_alembic("downgrade", "0007_organizations_memberships").returncode, 0)
        async with self.engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM transcripts WHERE meeting_id = :id AND revision_number = 2"),
                {"id": self.meeting_id},
            )
        self._alembic("downgrade", "0007_organizations_memberships")
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(
                    text("SELECT id, segments FROM transcripts WHERE id = :id"),
                    {"id": self.transcript_id},
                )
            ).one()
            self.assertEqual(row.id, self.transcript_id)
            self.assertEqual(row.segments[0]["text"], "original")
        self._alembic("upgrade", "head")
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(
                    text("SELECT id, revision_number FROM transcripts WHERE id = :id"),
                    {"id": self.transcript_id},
                )
            ).one()
            self.assertEqual((row.id, row.revision_number), (self.transcript_id, 1))


if __name__ == "__main__":
    unittest.main()
