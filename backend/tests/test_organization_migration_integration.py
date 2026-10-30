"""Opt-in organization migration checks for a dedicated disposable PostgreSQL database."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

REPOSITORY_ROOT = Path(__file__).resolve().parents[1].parent
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _validate_disposable_database_url(
    configured_test_url: str | None,
    configured_database_url: str | None,
) -> tuple[str, str]:
    """Return the explicit disposable URL and DB name without exposing credentials."""
    if not configured_test_url:
        raise ValueError("ORGANIZATION_MIGRATION_TEST_DATABASE_URL is required; no fallback is permitted.")
    try:
        parsed_url = make_url(configured_test_url)
    except Exception as error:
        raise ValueError("The dedicated migration test URL is invalid.") from error
    database_name = parsed_url.database or ""
    if parsed_url.get_backend_name() != "postgresql":
        raise ValueError("The migration test URL must use PostgreSQL.")
    if not database_name.endswith("_disposable_test"):
        raise ValueError("The migration test database name must end in _disposable_test.")
    if configured_database_url:
        try:
            configured_database_name = make_url(configured_database_url).database
        except Exception:
            configured_database_name = None
        if configured_database_name == database_name:
            raise ValueError("The migration test database must differ from DATABASE_URL.")
    return configured_test_url, database_name


class OrganizationMigrationSafetyTestCase(unittest.TestCase):
    def test_database_url_is_required_and_never_falls_back(self) -> None:
        with self.assertRaisesRegex(ValueError, "no fallback"):
            _validate_disposable_database_url(None, "postgresql://dev/db")

    def test_database_name_must_be_disposable_and_backend_postgresql(self) -> None:
        with self.assertRaisesRegex(ValueError, "end in _disposable_test"):
            _validate_disposable_database_url("postgresql://host/ordinary", None)
        with self.assertRaisesRegex(ValueError, "must use PostgreSQL"):
            _validate_disposable_database_url("sqlite:///project_disposable_test", None)

    def test_test_database_cannot_match_the_normal_database_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "must differ from DATABASE_URL"):
            _validate_disposable_database_url(
                "postgresql://user:secret@host/project_disposable_test",
                "postgresql://other:secret@other-host/project_disposable_test",
            )

    def test_credentials_are_not_in_validation_errors(self) -> None:
        with self.assertRaises(ValueError) as context:
            _validate_disposable_database_url(
                "postgresql://sensitive-user:sensitive-password@host/ordinary",
                None,
            )
        self.assertNotIn("sensitive-user", str(context.exception))
        self.assertNotIn("sensitive-password", str(context.exception))


@unittest.skipUnless(
    os.environ.get("RUN_ORGANIZATION_MIGRATION_INTEGRATION") == "1",
    "Set RUN_ORGANIZATION_MIGRATION_INTEGRATION=1 for disposable PostgreSQL migration verification.",
)
class OrganizationMigrationIntegrationTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        configured_test_url = os.environ.get("ORGANIZATION_MIGRATION_TEST_DATABASE_URL")
        try:
            self.database_url, database_name = _validate_disposable_database_url(
                configured_test_url,
                os.environ.get("DATABASE_URL"),
            )
        except ValueError as error:
            self.fail(str(error))

        self.engine = create_async_engine(self.database_url)
        self.migration_started = False
        try:
            async with self.engine.connect() as connection:
                actual_database = await connection.scalar(text("SELECT current_database()"))
                if actual_database != database_name:
                    self.fail("Connected database name did not match the validated URL name.")
                table_names = await connection.run_sync(
                    lambda sync_connection: inspect(sync_connection).get_table_names()
                )
            if table_names:
                self.fail("Dedicated disposable migration database must contain no tables or user data.")

            self._alembic("upgrade", "0006_processing_jobs")
            self.migration_started = True
            self.user_ids = [uuid.uuid4(), uuid.uuid4()]
            self.legacy_organization_id = uuid.uuid4()
            self.meeting_id = uuid.uuid4()
            async with self.engine.begin() as connection:
                for index, user_id in enumerate(self.user_ids):
                    await connection.execute(
                        text(
                            "INSERT INTO users (id, email, password_hash) "
                            "VALUES (:id, :email, 'migration-test-hash')"
                        ),
                        {"id": user_id, "email": f"org-migration-{index}-{user_id}@example.test"},
                    )
                await connection.execute(
                    text(
                        "INSERT INTO meetings (id, organization_id, created_by, title, participants, status) "
                        "VALUES (:id, :organization_id, :created_by, 'Legacy', '[]'::jsonb, 'pending')"
                    ),
                    {
                        "id": self.meeting_id,
                        "organization_id": self.legacy_organization_id,
                        "created_by": self.user_ids[0],
                    },
                )
            self._alembic("upgrade", "head")
        except BaseException:
            if self.migration_started:
                try:
                    self._alembic("downgrade", "base")
                except Exception:
                    pass
            await self.engine.dispose()
            raise

    async def asyncTearDown(self) -> None:
        try:
            if self.migration_started:
                self._alembic("downgrade", "base")
        finally:
            await self.engine.dispose()

    def _alembic(self, direction: str, revision: str) -> None:
        # Alembic reads DATABASE_URL. Set it only from the separately validated
        # disposable-test URL; never inherit or fall back to the normal URL.
        environment = os.environ.copy()
        environment["DATABASE_URL"] = self.database_url
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", direction, revision],
            cwd=REPOSITORY_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            self.fail(f"Alembic {direction} {revision} failed; URL and command output are suppressed.")

    async def _assert_database_rejects(
        self,
        connection,
        statement: str,
        parameters: dict[str, object],
        *,
        expected_exception: type[Exception] = IntegrityError,
    ) -> Exception:
        with self.assertRaises(expected_exception) as raised:
            async with connection.begin_nested():
                await connection.execute(text(statement), parameters)
        return raised.exception

    async def test_constraints_backfill_preservation_downgrade_and_reupgrade(self) -> None:
        async with self.engine.begin() as connection:
            personal_rows = (
                await connection.execute(
                    text(
                        "SELECT o.id, o.name, o.personal_owner_user_id, m.user_id, m.role "
                        "FROM organizations o JOIN organization_memberships m ON m.organization_id = o.id "
                        "WHERE o.personal_owner_user_id = ANY(:user_ids) ORDER BY o.personal_owner_user_id"
                    ),
                    {"user_ids": self.user_ids},
                )
            ).all()
            self.assertEqual(len(personal_rows), len(self.user_ids))
            self.assertEqual(
                {row.personal_owner_user_id for row in personal_rows}, set(self.user_ids)
            )
            self.assertEqual(
                {row.user_id for row in personal_rows}, set(self.user_ids)
            )
            self.assertTrue(all(row.name == "Personal workspace" for row in personal_rows))
            self.assertTrue(all(row.role == "owner" for row in personal_rows))
            personal_org_ids = [row.id for row in personal_rows]
            self.assertEqual(len(set(personal_org_ids)), len(self.user_ids))
            personal_org_by_user = {
                row.personal_owner_user_id: row.id for row in personal_rows
            }

            existing_user_ids = set(
                (
                    await connection.execute(
                        text("SELECT id FROM users WHERE id = ANY(:ids)"),
                        {"ids": self.user_ids},
                    )
                ).scalars()
            )
            self.assertEqual(existing_user_ids, set(self.user_ids))
            meeting = (
                await connection.execute(
                    text("SELECT id, organization_id, created_by FROM meetings WHERE id = :id"),
                    {"id": self.meeting_id},
                )
            ).one()
            self.assertEqual(meeting.id, self.meeting_id)
            self.assertEqual(meeting.organization_id, self.legacy_organization_id)
            self.assertEqual(meeting.created_by, self.user_ids[0])
            historical_memberships = await connection.scalar(
                text("SELECT count(*) FROM organization_memberships WHERE organization_id = :id"),
                {"id": self.legacy_organization_id},
            )
            self.assertEqual(historical_memberships, 0)
            # Exercise actual PostgreSQL constraints, not ORM validators.
            await self._assert_database_rejects(
                connection,
                "INSERT INTO organization_memberships (organization_id, user_id, role) "
                "VALUES (:organization_id, :user_id, 'owner')",
                {
                    "organization_id": personal_org_by_user[self.user_ids[0]],
                    "user_id": self.user_ids[0],
                },
            )
            invalid_role_error = await self._assert_database_rejects(
                connection,
                "INSERT INTO organization_memberships (organization_id, user_id, role) "
                "VALUES (:organization_id, :user_id, 'invalid_role')",
                {
                    "organization_id": personal_org_by_user[self.user_ids[0]],
                    "user_id": self.user_ids[0],
                },
                expected_exception=DBAPIError,
            )
            self.assertEqual(getattr(invalid_role_error.orig, "sqlstate", None), "22P02")
            await self._assert_database_rejects(
                connection,
                "INSERT INTO organization_memberships (organization_id, user_id, role) "
                "VALUES (:organization_id, :user_id, 'member')",
                {
                    "organization_id": personal_org_by_user[self.user_ids[0]],
                    "user_id": uuid.uuid4(),
                },
            )
            await self._assert_database_rejects(
                connection,
                "INSERT INTO organization_memberships (organization_id, user_id, role) "
                "VALUES (:organization_id, :user_id, 'member')",
                {"organization_id": uuid.uuid4(), "user_id": self.user_ids[0]},
            )
            await self._assert_database_rejects(
                connection,
                "INSERT INTO organizations (id, name, personal_owner_user_id) "
                "VALUES (:id, 'Duplicate personal', :user_id)",
                {"id": uuid.uuid4(), "user_id": self.user_ids[0]},
            )

            # PostgreSQL UNIQUE permits multiple NULLs; these are non-personal
            # organizations and carry no personal-owner identity.
            null_org_ids = [uuid.uuid4(), uuid.uuid4()]
            for organization_id in null_org_ids:
                await connection.execute(
                    text(
                        "INSERT INTO organizations (id, name, personal_owner_user_id) "
                        "VALUES (:id, 'Non-personal test organization', NULL)"
                    ),
                    {"id": organization_id},
                )
            null_count = await connection.scalar(
                text("SELECT count(*) FROM organizations WHERE personal_owner_user_id IS NULL")
            )
            self.assertGreaterEqual(null_count, 2)

            cascade_org_id, cascade_org_user_id = uuid.uuid4(), uuid.uuid4()
            await connection.execute(
                text("INSERT INTO users (id, email, password_hash) VALUES (:id, :email, 'test-hash')"),
                {"id": cascade_org_user_id, "email": f"cascade-org-{cascade_org_user_id}@example.test"},
            )
            await connection.execute(
                text("INSERT INTO organizations (id, name) VALUES (:id, 'Cascade test organization')"),
                {"id": cascade_org_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO organization_memberships (organization_id, user_id, role) "
                    "VALUES (:organization_id, :user_id, 'member')"
                ),
                {"organization_id": cascade_org_id, "user_id": cascade_org_user_id},
            )
            await connection.execute(
                text("DELETE FROM organizations WHERE id = :id"), {"id": cascade_org_id}
            )
            self.assertEqual(
                await connection.scalar(
                    text("SELECT count(*) FROM organization_memberships WHERE organization_id = :id"),
                    {"id": cascade_org_id},
                ),
                0,
            )

            cascade_user_id, cascade_user_org_id = uuid.uuid4(), uuid.uuid4()
            await connection.execute(
                text("INSERT INTO users (id, email, password_hash) VALUES (:id, :email, 'test-hash')"),
                {"id": cascade_user_id, "email": f"cascade-user-{cascade_user_id}@example.test"},
            )
            await connection.execute(
                text(
                    "INSERT INTO organizations (id, name, personal_owner_user_id) "
                    "VALUES (:id, 'Cascade user organization', :user_id)"
                ),
                {"id": cascade_user_org_id, "user_id": cascade_user_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO organization_memberships (organization_id, user_id, role) "
                    "VALUES (:organization_id, :user_id, 'owner')"
                ),
                {"organization_id": cascade_user_org_id, "user_id": cascade_user_id},
            )
            await connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": cascade_user_id})
            self.assertEqual(
                await connection.scalar(
                    text("SELECT count(*) FROM organization_memberships WHERE user_id = :id"),
                    {"id": cascade_user_id},
                ),
                0,
            )
            self.assertEqual(
                await connection.scalar(
                    text("SELECT count(*) FROM organizations WHERE id = :id"),
                    {"id": cascade_user_org_id},
                ),
                0,
            )

        self._alembic("downgrade", "0006_processing_jobs")
        async with self.engine.connect() as connection:
            remaining_user_ids = set(
                (
                    await connection.execute(
                        text("SELECT id FROM users WHERE id = ANY(:ids)"),
                        {"ids": self.user_ids},
                    )
                ).scalars()
            )
            self.assertEqual(remaining_user_ids, set(self.user_ids))
            preserved_meeting = (
                await connection.execute(
                    text("SELECT id, organization_id FROM meetings WHERE id = :id"),
                    {"id": self.meeting_id},
                )
            ).one()
            self.assertEqual(preserved_meeting.id, self.meeting_id)
            self.assertEqual(preserved_meeting.organization_id, self.legacy_organization_id)
            table_names = await connection.run_sync(
                lambda sync_connection: set(inspect(sync_connection).get_table_names())
            )
            self.assertNotIn("organizations", table_names)
            self.assertNotIn("organization_memberships", table_names)

        self._alembic("upgrade", "head")
        async with self.engine.connect() as connection:
            for user_id in self.user_ids:
                count = await connection.scalar(
                    text(
                        "SELECT count(*) FROM organizations o "
                        "JOIN organization_memberships m ON m.organization_id = o.id "
                        "WHERE o.personal_owner_user_id = :user_id "
                        "AND m.user_id = :user_id AND m.role = 'owner'"
                    ),
                    {"user_id": user_id},
                )
                self.assertEqual(count, 1)
            preserved_meeting = (
                await connection.execute(
                    text("SELECT id, organization_id FROM meetings WHERE id = :id"),
                    {"id": self.meeting_id},
                )
            ).one()
            self.assertEqual(preserved_meeting.id, self.meeting_id)
            self.assertEqual(preserved_meeting.organization_id, self.legacy_organization_id)
