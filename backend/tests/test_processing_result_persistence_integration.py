"""Opt-in PostgreSQL verification for atomic worker result persistence."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

REPOSITORY_ROOT = Path(__file__).resolve().parents[1].parent
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
MEETING_ROOT = BACKEND_ROOT / "meeting-service"
for _root in (BACKEND_ROOT, MEETING_ROOT):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))


def _validate_disposable_database_url(
    configured: str | None, normal_database_url: str | None
) -> tuple[str, str]:
    """Require the dedicated disposable target; never use DATABASE_URL as target."""
    if not configured:
        raise ValueError(
            "PROCESSING_RESULT_PERSISTENCE_TEST_DATABASE_URL is required; "
            "no fallback is permitted."
        )
    try:
        parsed = make_url(configured)
    except Exception:
        raise ValueError("The processing-result test database URL is invalid.") from None
    database_name = parsed.database or ""
    if parsed.get_backend_name() != "postgresql":
        raise ValueError("The processing-result test database must use PostgreSQL.")
    if not database_name.endswith("_disposable_test"):
        raise ValueError(
            "The processing-result test database name must end in _disposable_test."
        )
    if normal_database_url:
        try:
            normal_name = make_url(normal_database_url).database
        except Exception:
            raise ValueError("DATABASE_URL is invalid for the safety comparison.") from None
        if normal_name == database_name:
            raise ValueError(
                "The processing-result test database must differ from DATABASE_URL."
            )
    return configured, database_name


def _safe_alembic_error(
    result: subprocess.CompletedProcess[str], database_url: str
) -> str:
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    output = output.replace(database_url, "<database-url-redacted>")
    try:
        parsed = make_url(database_url)
        if parsed.password:
            output = output.replace(parsed.password, "<password-redacted>")
        if parsed.username:
            output = output.replace(parsed.username, "<username-redacted>")
    except Exception:
        pass
    output = re.sub(
        r"(?i)postgres(?:ql)?(?:\+[a-z0-9_]+)?://[^\s\"'<>]+",
        "<database-url-redacted>",
        output,
    )
    lines = [line for line in output.splitlines() if line.strip()]
    return "\n".join(lines[-16:]) or "Alembic produced no diagnostic output."


def _assert_clean_database_state(table_names: list[str], version_rows: int) -> None:
    unexpected = set(table_names) - {"alembic_version"}
    if unexpected:
        raise RuntimeError(
            "The disposable result-persistence database must contain no application tables."
        )
    if "alembic_version" in table_names and version_rows:
        raise RuntimeError(
            "The disposable result-persistence database must have no active Alembic revision."
        )


class ProcessingResultPersistenceSafetyTests(unittest.TestCase):
    def test_requires_explicit_disposable_target_without_fallback(self) -> None:
        with self.assertRaisesRegex(ValueError, "no fallback"):
            _validate_disposable_database_url(None, "postgresql://host/ordinary")

    def test_rejects_non_postgresql_or_non_disposable_database(self) -> None:
        with self.assertRaisesRegex(ValueError, "PostgreSQL"):
            _validate_disposable_database_url("sqlite:///safe_disposable_test", None)
        with self.assertRaisesRegex(ValueError, "end in _disposable_test"):
            _validate_disposable_database_url("postgresql://host/ordinary", None)

    def test_rejects_database_name_matching_normal_database_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "differ from DATABASE_URL"):
            _validate_disposable_database_url(
                "postgresql://test:secret@localhost/app_disposable_test",
                "postgresql://dev:secret@otherhost/app_disposable_test",
            )

    def test_clean_state_allows_only_empty_alembic_bookkeeping(self) -> None:
        _assert_clean_database_state([], 0)
        _assert_clean_database_state(["alembic_version"], 0)
        with self.assertRaisesRegex(RuntimeError, "no application tables"):
            _assert_clean_database_state(["alembic_version", "users"], 0)
        with self.assertRaisesRegex(RuntimeError, "no active Alembic revision"):
            _assert_clean_database_state(["alembic_version"], 1)


@unittest.skipUnless(
    os.environ.get("RUN_PROCESSING_RESULT_PERSISTENCE_INTEGRATION") == "1",
    "Set RUN_PROCESSING_RESULT_PERSISTENCE_INTEGRATION=1 for disposable PostgreSQL verification.",
)
class ProcessingResultPersistencePostgresIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.database_url, self.database_name = _validate_disposable_database_url(
            os.environ.get("PROCESSING_RESULT_PERSISTENCE_TEST_DATABASE_URL"),
            os.environ.get("DATABASE_URL"),
        )
        self.engine = create_async_engine(self.database_url, pool_pre_ping=True)
        self.migrations_attempted = False
        try:
            await self._verify_empty_disposable_database()
            self.migrations_attempted = True
            self._alembic("upgrade", "0006_processing_jobs")
            await self._insert_user_before_organization_migration()
            self._alembic("upgrade", "head")
            self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
            await self._insert_meeting_and_transcript()
        except BaseException as setup_error:
            cleanup_error = None
            if self.migrations_attempted:
                try:
                    await self._downgrade_and_verify_clean()
                except Exception as error:
                    cleanup_error = error
            await self.engine.dispose()
            if cleanup_error is not None:
                raise RuntimeError(
                    f"Integration setup failed ({type(setup_error).__name__}); "
                    f"disposable database cleanup also failed ({type(cleanup_error).__name__})."
                ) from None
            raise

    async def asyncTearDown(self) -> None:
        try:
            if self.migrations_attempted:
                await self._downgrade_and_verify_clean()
        finally:
            await self.engine.dispose()

    async def _verify_empty_disposable_database(self) -> None:
        async with self.engine.connect() as connection:
            actual_name = await connection.scalar(text("SELECT current_database()"))
            if actual_name != self.database_name or not actual_name.endswith(
                "_disposable_test"
            ):
                raise RuntimeError(
                    "Connected database does not match the validated disposable target."
                )
            table_names = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_table_names()
            )
            version_rows = 0
            if "alembic_version" in table_names:
                version_rows = await connection.scalar(
                    text("SELECT count(*) FROM alembic_version")
                )
            _assert_clean_database_state(table_names, int(version_rows or 0))

    async def _insert_user_before_organization_migration(self) -> None:
        self.owner_id = uuid.uuid4()
        async with self.engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users (id, email, password_hash) "
                    "VALUES (:id, :email, 'result-persistence-test-hash')"
                ),
                {
                    "id": self.owner_id,
                    "email": f"result-persistence-{self.owner_id}@example.test",
                },
            )

    async def _insert_meeting_and_transcript(self) -> None:
        from shared.database.models.meeting import Meeting
        from shared.database.models.organization import Organization
        from shared.database.models.transcript import Transcript

        self.meeting_id = uuid.uuid4()
        self.transcript_id = uuid.uuid4()
        async with self.sessions() as session:
            organization = await session.scalar(
                select(Organization).where(
                    Organization.personal_owner_user_id == self.owner_id
                )
            )
            if organization is None:
                raise RuntimeError("Organization migration did not provision test ownership.")
            session.add_all(
                [
                    Meeting(
                        id=self.meeting_id,
                        organization_id=organization.id,
                        created_by=self.owner_id,
                        title="Processing result persistence integration",
                        participants=[],
                    ),
                    Transcript(
                        id=self.transcript_id,
                        meeting_id=self.meeting_id,
                        revision_number=1,
                        segments=[{"index": 0, "text": "Review the delivery plan."}],
                        language="en",
                    ),
                ]
            )
            await session.commit()

    async def _downgrade_and_verify_clean(self) -> None:
        await self._verify_database_identity()
        self._alembic("downgrade", "base")
        async with self.engine.connect() as connection:
            actual_name = await connection.scalar(text("SELECT current_database()"))
            if actual_name != self.database_name or not actual_name.endswith(
                "_disposable_test"
            ):
                raise RuntimeError("Refusing cleanup outside the validated disposable database.")
            table_names = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_table_names()
            )
            version_rows = 0
            if "alembic_version" in table_names:
                version_rows = await connection.scalar(
                    text("SELECT count(*) FROM alembic_version")
                )
            _assert_clean_database_state(table_names, int(version_rows or 0))

    async def _verify_database_identity(self) -> None:
        async with self.engine.connect() as connection:
            actual_name = await connection.scalar(text("SELECT current_database()"))
        if actual_name != self.database_name or not actual_name.endswith(
            "_disposable_test"
        ):
            raise RuntimeError("Refusing migration operation outside the validated disposable database.")

    def _alembic(self, direction: str, revision: str) -> None:
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
        if result.returncode:
            detail = _safe_alembic_error(result, self.database_url)
            raise RuntimeError(
                f"Alembic {direction} {revision} failed (exit {result.returncode}):\n{detail}"
            )

    async def _register_and_claim(self, operations: list[str]):
        from shared.jobs.lifecycle import ProcessingJobService
        from shared.jobs.repository import ProcessingJobRepository
        from shared.jobs.lifecycle import JobStatus

        job_id = uuid.uuid4()
        async with self.sessions() as session:
            service = ProcessingJobService(
                session,
                ProcessingJobRepository(session),
                lease_seconds=60,
                completed_result_persister=_result_persister,
            )
            await service.register(
                job_id=job_id,
                meeting_id=self.meeting_id,
                transcript_id=self.transcript_id,
                owner_id=self.owner_id,
                requested_operations=operations,
            )
            claim = await service.claim(
                job_id=job_id,
                meeting_id=self.meeting_id,
                transcript_id=self.transcript_id,
                owner_id=self.owner_id,
                requested_operations=operations,
            )
            self.assertEqual(claim.status, JobStatus.RUNNING)
            return job_id, claim.lease_token

    async def _complete(self, job_id, lease_token, result, status):
        from shared.jobs.lifecycle import ProcessingJobService
        from shared.jobs.repository import ProcessingJobRepository

        async with self.sessions() as session:
            service = ProcessingJobService(
                session,
                ProcessingJobRepository(session),
                lease_seconds=60,
                completed_result_persister=_result_persister,
            )
            return await service.complete(
                job_id, lease_token, status=status, result=result
            )

    async def _counts(self, job_id):
        from shared.database.models.decision import Decision
        from shared.database.models.followup import Followup
        from shared.database.models.meeting_insight import MeetingInsight
        from shared.database.models.processing_job import ProcessingJobRecord
        from shared.database.models.summary import Summary
        from shared.database.models.task import Task

        async with self.sessions() as session:
            record = await session.get(ProcessingJobRecord, job_id)
            counts = {
                "summaries": await session.scalar(
                    select(func.count()).select_from(Summary).where(Summary.meeting_id == self.meeting_id)
                ),
                "tasks": await session.scalar(
                    select(func.count()).select_from(Task).where(Task.meeting_id == self.meeting_id)
                ),
                "decisions": await session.scalar(
                    select(func.count()).select_from(Decision).where(Decision.meeting_id == self.meeting_id)
                ),
                "followups": await session.scalar(
                    select(func.count()).select_from(Followup).where(Followup.meeting_id == self.meeting_id)
                ),
                "insights": await session.scalar(
                    select(func.count()).select_from(MeetingInsight).where(MeetingInsight.meeting_id == self.meeting_id)
                ),
            }
            return record, {name: int(value or 0) for name, value in counts.items()}

    async def test_terminal_job_json_and_all_domain_rows_commit_atomically(self) -> None:
        from shared.jobs.lifecycle import JobStatus

        operations = ["summary", "tasks", "decisions", "follow_ups", "insights"]
        job_id, lease = await self._register_and_claim(operations)
        result = _processing_result(self.meeting_id, self.transcript_id, operations)
        self.assertTrue(
            await self._complete(job_id, lease, result, JobStatus.COMPLETED)
        )
        record, counts = await self._counts(job_id)
        self.assertEqual(record.status, JobStatus.COMPLETED.value)
        self.assertEqual(record.result, result)
        self.assertEqual(
            counts,
            {"summaries": 1, "tasks": 1, "decisions": 1, "followups": 1, "insights": 1},
        )

    async def test_domain_failure_rolls_back_rows_result_json_and_terminal_status(self) -> None:
        from shared.jobs.lifecycle import JobStatus, ProcessingJobService
        from shared.jobs.repository import ProcessingJobRepository
        from app.services.processing_result_persistence import persist_processing_result

        operations = ["summary", "tasks"]
        job_id, lease = await self._register_and_claim(operations)
        result = _processing_result(self.meeting_id, self.transcript_id, operations)

        async def persist_then_fail(session, record, payload):
            await persist_processing_result(session, record, payload)
            raise RuntimeError("injected persistence failure")

        async with self.sessions() as session:
            service = ProcessingJobService(
                session,
                ProcessingJobRepository(session),
                lease_seconds=60,
                completed_result_persister=persist_then_fail,
            )
            with self.assertRaisesRegex(RuntimeError, "injected persistence failure"):
                await service.complete(job_id, lease, status=JobStatus.COMPLETED, result=result)

        record, counts = await self._counts(job_id)
        self.assertEqual(record.status, JobStatus.RUNNING.value)
        self.assertIsNone(record.result)
        self.assertEqual(sum(counts.values()), 0)

    async def test_duplicate_completion_does_not_duplicate_domain_rows(self) -> None:
        from shared.jobs.lifecycle import JobStatus

        operations = ["summary", "tasks"]
        job_id, lease = await self._register_and_claim(operations)
        result = _processing_result(self.meeting_id, self.transcript_id, operations)
        self.assertTrue(
            await self._complete(job_id, lease, result, JobStatus.COMPLETED)
        )
        self.assertFalse(
            await self._complete(job_id, lease, result, JobStatus.COMPLETED)
        )
        record, counts = await self._counts(job_id)
        self.assertEqual(record.status, JobStatus.COMPLETED.value)
        self.assertEqual(counts["summaries"], 1)
        self.assertEqual(counts["tasks"], 1)

    async def test_partial_result_persists_only_successful_operations(self) -> None:
        from shared.jobs.lifecycle import JobStatus

        operations = ["summary", "tasks"]
        job_id, lease = await self._register_and_claim(operations)
        result = _processing_result(self.meeting_id, self.transcript_id, operations)
        result["status"] = "partially_failed"
        result["results"][1] = {
            "operation": "tasks",
            "status": "failed",
            "output": None,
            "error": {"code": "provider_timeout", "message": "The model provider timed out."},
        }
        self.assertTrue(
            await self._complete(job_id, lease, result, JobStatus.PARTIAL)
        )
        record, counts = await self._counts(job_id)
        self.assertEqual(record.status, JobStatus.PARTIAL.value)
        self.assertEqual(record.result, result)
        self.assertEqual(counts["summaries"], 1)
        self.assertEqual(counts["tasks"], 0)


async def _result_persister(session, record, result):
    from app.services.processing_result_persistence import persist_processing_result

    await persist_processing_result(session, record, result)


def _processing_result(meeting_id: uuid.UUID, transcript_id: uuid.UUID, operations: list[str]) -> dict[str, Any]:
    outputs: dict[str, dict[str, Any]] = {
        "summary": {
            "meeting_id": str(meeting_id), "content": "Persisted summary",
            "key_topics": ["delivery"], "model_provider": None, "model_name": None,
        },
        "tasks": {"items": [{
            "meeting_id": str(meeting_id), "title": "Review plan", "description": None,
            "assignee_id": None, "due_at": None,
        }]},
        "decisions": {"items": [{
            "meeting_id": str(meeting_id), "statement": "Keep scope", "context": None,
            "participants": [],
        }]},
        "follow_ups": {"items": [{
            "meeting_id": str(meeting_id), "subject": "Meeting notes",
            "body_html": "<p>Notes</p>", "recipients": ["person@example.com"],
        }]},
        "insights": {"items": [{
            "meeting_id": str(meeting_id), "category": "risk",
            "title": "Schedule risk", "description": "Delivery date is at risk.",
        }]},
    }
    return {
        "meeting_id": str(meeting_id),
        "transcript_id": str(transcript_id),
        "requested_operations": operations,
        "status": "completed",
        "results": [
            {
                "operation": operation,
                "status": "completed",
                "output": outputs[operation],
                "error": None,
            }
            for operation in operations
        ],
    }


if __name__ == "__main__":
    unittest.main()
