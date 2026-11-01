"""Opt-in transactional submission verification on empty disposable PostgreSQL."""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))
from meeting_service_test_support import prepare_meeting_service_imports

REPOSITORY_ROOT = Path(__file__).resolve().parents[1].parent
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
MEETING_ROOT = BACKEND_ROOT / "meeting-service"
for path in (BACKEND_ROOT, MEETING_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _validate_test_database_url(configured: str | None, normal: str | None) -> tuple[str, str]:
    if not configured:
        raise ValueError("ATOMIC_MEETING_SUBMISSION_TEST_DATABASE_URL is required; no fallback is permitted.")
    try:
        parsed = make_url(configured)
    except Exception as error:
        raise ValueError("The atomic-submission test database URL is invalid.") from error
    database_name = parsed.database or ""
    if parsed.get_backend_name() != "postgresql":
        raise ValueError("The atomic-submission test database must use PostgreSQL.")
    if not database_name.endswith("_disposable_test"):
        raise ValueError("The atomic-submission test database name must end in _disposable_test.")
    if normal:
        try:
            normal_database = make_url(normal).database
        except Exception:
            normal_database = None
        if normal_database == database_name:
            raise ValueError("The atomic-submission test database must differ from DATABASE_URL.")
    return configured, database_name


def _safe_alembic_error(result: subprocess.CompletedProcess[str], database_url: str) -> str:
    """Return useful Alembic diagnostics without emitting connection credentials."""
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


async def _remove_test_created_extra_transcript_revisions(
    engine, *, expected_database_name: str, owner_ids: list[uuid.UUID]
) -> None:
    """Make revision downgrade safe, only in the verified disposable database."""
    if not owner_ids:
        return
    async with engine.begin() as connection:
        actual_name = await connection.scalar(text("SELECT current_database()"))
        if actual_name != expected_database_name or not actual_name.endswith("_disposable_test"):
            raise RuntimeError("Refusing transcript cleanup outside the verified disposable database.")
        has_revision_column = await connection.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = 'transcripts' "
                "AND column_name = 'revision_number')"
            )
        )
        if has_revision_column:
            await connection.execute(
                text(
                    "DELETE FROM transcripts AS transcript "
                    "USING meetings AS meeting "
                    "WHERE transcript.meeting_id = meeting.id "
                    "AND meeting.created_by = ANY(:owner_ids) "
                    "AND transcript.revision_number > 1"
                ),
                {"owner_ids": owner_ids},
            )


def _assert_clean_database_state(table_names: list[str], version_rows: int) -> None:
    # Alembic leaves its version table behind after downgrading to base. It is
    # safe to reuse only when that bookkeeping table is empty and no app table
    # remains.
    unexpected_tables = set(table_names) - {"alembic_version"}
    if unexpected_tables:
        raise RuntimeError("Dedicated disposable submission-test database must contain no application tables.")
    if "alembic_version" in table_names and version_rows != 0:
        raise RuntimeError("Dedicated disposable submission-test database has an active Alembic revision.")


async def _assert_clean_disposable_database(connection, expected_database_name: str) -> None:
    actual_name = await connection.scalar(text("SELECT current_database()"))
    if actual_name != expected_database_name or not actual_name.endswith("_disposable_test"):
        raise RuntimeError("Connected database does not match the verified disposable database name.")
    table_names = await connection.run_sync(
        lambda sync_connection: inspect(sync_connection).get_table_names()
    )
    version_rows = 0
    if "alembic_version" in table_names:
        version_rows = await connection.scalar(text("SELECT count(*) FROM alembic_version"))
    _assert_clean_database_state(table_names, version_rows or 0)


class _FakeConnection:
    def __init__(self, database_name: str, has_revision_column: bool = True) -> None:
        self.database_name = database_name
        self.has_revision_column = has_revision_column
        self.executed: list[tuple[str, object]] = []

    async def scalar(self, statement):
        sql = str(statement)
        if "current_database()" in sql:
            return self.database_name
        return self.has_revision_column

    async def execute(self, statement, parameters=None):
        self.executed.append((str(statement), parameters))


class _FakeTransaction:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_args):
        return False


class _FakeEngine:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def begin(self):
        return _FakeTransaction(self.connection)


def _run_immediate_coroutine(coroutine):
    """Drive the fully mocked cleanup coroutine without initializing sockets."""
    try:
        yielded = coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError(f"Mocked cleanup unexpectedly suspended on {yielded!r}.")


class AtomicMeetingSubmissionSafetyTestCase(unittest.TestCase):
    def test_database_url_is_explicit_and_disposable(self) -> None:
        with self.assertRaisesRegex(ValueError, "no fallback"):
            _validate_test_database_url(None, "postgresql://host/ordinary")
        with self.assertRaisesRegex(ValueError, "end in _disposable_test"):
            _validate_test_database_url(
                "postgresql://user:secret@host/ordinary", None
            )
        with self.assertRaisesRegex(ValueError, "must differ"):
            _validate_test_database_url(
                "postgresql://host/project_disposable_test",
                "postgresql://other/project_disposable_test",
            )

    def test_alembic_error_reports_migration_detail_without_credentials(self) -> None:
        database_url = "postgresql+asyncpg://dbuser:dbsecret@localhost/submission_disposable_test"
        result = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr=(
                "Traceback (most recent call last):\n"
                "sqlalchemy.exc.RuntimeError: Cannot downgrade transcript revisions "
                "while meetings have multiple revisions.\n"
                f"Connection was {database_url}\n"
            ),
        )
        detail = _safe_alembic_error(result, database_url)
        self.assertIn("Cannot downgrade transcript revisions", detail)
        self.assertIn("multiple revisions", detail)
        self.assertNotIn("dbsecret", detail)
        self.assertNotIn(database_url, detail)

    def test_revision_cleanup_is_scoped_and_rechecks_database_name(self) -> None:
        owner_id = uuid.uuid4()
        database_name = "submission_disposable_test"
        connection = _FakeConnection(database_name)
        _run_immediate_coroutine(
            _remove_test_created_extra_transcript_revisions(
                _FakeEngine(connection),
                expected_database_name=database_name,
                owner_ids=[owner_id],
            )
        )
        self.assertEqual(len(connection.executed), 1)
        statement, parameters = connection.executed[0]
        self.assertIn("meeting.created_by = ANY", statement)
        self.assertIn("transcript.revision_number > 1", statement)
        self.assertEqual(parameters, {"owner_ids": [owner_id]})

        wrong_database = _FakeConnection("ordinary_development")
        with self.assertRaisesRegex(RuntimeError, "Refusing transcript cleanup"):
            _run_immediate_coroutine(
                _remove_test_created_extra_transcript_revisions(
                    _FakeEngine(wrong_database),
                    expected_database_name=database_name,
                    owner_ids=[owner_id],
                )
            )
        self.assertEqual(wrong_database.executed, [])

    def test_downgraded_database_is_reusable_with_only_empty_alembic_bookkeeping(self) -> None:
        _assert_clean_database_state(["alembic_version"], 0)
        _assert_clean_database_state([], 0)
        with self.assertRaisesRegex(RuntimeError, "application tables"):
            _assert_clean_database_state(["alembic_version", "users"], 0)
        with self.assertRaisesRegex(RuntimeError, "active Alembic revision"):
            _assert_clean_database_state(["alembic_version"], 1)


@unittest.skipUnless(
    os.environ.get("RUN_ATOMIC_MEETING_SUBMISSION_INTEGRATION") == "1",
    "Set RUN_ATOMIC_MEETING_SUBMISSION_INTEGRATION=1 for disposable PostgreSQL verification.",
)
class AtomicMeetingSubmissionIntegrationTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        prepare_meeting_service_imports()
        try:
            self.database_url, database_name = _validate_test_database_url(
                os.environ.get("ATOMIC_MEETING_SUBMISSION_TEST_DATABASE_URL"),
                os.environ.get("DATABASE_URL"),
            )
            self.test_database_name = database_name
        except ValueError as error:
            self.fail(str(error))
        self.engine = create_async_engine(self.database_url)
        self.migration_started = False
        try:
            async with self.engine.connect() as connection:
                await _assert_clean_disposable_database(connection, database_name)

            self._alembic("upgrade", "0006_processing_jobs")
            self.migration_started = True
            self.user_ids = [uuid.uuid4(), uuid.uuid4()]
            async with self.engine.begin() as connection:
                for index, user_id in enumerate(self.user_ids):
                    await connection.execute(
                        text(
                            "INSERT INTO users (id, email, password_hash) "
                            "VALUES (:id, :email, 'atomic-submission-test-hash')"
                        ),
                        {"id": user_id, "email": f"atomic-submission-{index}-{user_id}@example.test"},
                    )
            self._alembic("upgrade", "head")
            self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
            async with self.engine.connect() as connection:
                rows = (
                    await connection.execute(
                        text(
                            "SELECT personal_owner_user_id, id FROM organizations "
                            "WHERE personal_owner_user_id = ANY(:ids)"
                        ),
                        {"ids": self.user_ids},
                    )
                ).all()
            self.organization_ids = {row.personal_owner_user_id: row.id for row in rows}
            if set(self.organization_ids) != set(self.user_ids):
                self.fail("Migration did not provision both test personal organizations.")
        except BaseException as setup_error:
            cleanup_error = None
            if self.migration_started:
                try:
                    await self._cleanup_database()
                except Exception as error:
                    cleanup_error = error
            await self.engine.dispose()
            if cleanup_error is not None:
                safe_setup_error = _safe_alembic_error(
                    subprocess.CompletedProcess(
                        args=[], returncode=1, stdout="", stderr=str(setup_error)
                    ),
                    self.database_url,
                )
                raise RuntimeError(
                    f"Integration setup failed: {safe_setup_error}\n"
                    f"Disposable database cleanup also failed: {cleanup_error}"
                ) from None
            raise

    async def asyncTearDown(self) -> None:
        try:
            if self.migration_started:
                await self._cleanup_database()
        finally:
            await self.engine.dispose()

    async def _cleanup_database(self) -> None:
        await _remove_test_created_extra_transcript_revisions(
            self.engine,
            expected_database_name=self.test_database_name,
            owner_ids=getattr(self, "user_ids", []),
        )
        self._alembic("downgrade", "base")
        async with self.engine.connect() as connection:
            await _assert_clean_disposable_database(connection, self.test_database_name)

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
            detail = _safe_alembic_error(result, self.database_url)
            raise RuntimeError(
                f"Alembic {direction} {revision} failed (exit {result.returncode}):\n{detail}"
            )

    @staticmethod
    def _payload(organization_id: uuid.UUID, title: str = "Atomic submission"):
        from shared.schemas.meeting_submission import MeetingSubmissionRequest

        return MeetingSubmissionRequest.model_validate(
            {
                "meeting": {"organization_id": str(organization_id), "title": title},
                "transcript": {
                    "language": "en",
                    "segments": [
                        {"index": 0, "speaker": "Speaker A", "text": "Review the launch plan."}
                    ],
                },
                "requested_operations": ["summary", "tasks"],
            }
        )

    async def _submit(self, payload, owner_id: uuid.UUID, key: str):
        from app.repositories.meeting_repository import MeetingRepository
        from app.repositories.transcript_repository import TranscriptRepository
        from app.services.meeting_service import MeetingService

        async with self.sessions() as session:
            service = MeetingService(
                session,
                MeetingRepository(session),
                TranscriptRepository(session),
            )
            return await service.submit_meeting(payload, owner_id, key)

    async def test_atomicity_replay_ownership_rollback_revisions_and_concurrency(self) -> None:
        from sqlalchemy import func, select

        from shared.database.models.job_outbox_event import JobOutboxEvent
        from shared.database.models.meeting import Meeting
        from shared.database.models.meeting_submission_idempotency import MeetingSubmissionIdempotency
        from shared.database.models.processing_job import ProcessingJobRecord
        from shared.database.models.transcript import Transcript
        from shared.exceptions.common import ConflictError, ForbiddenError, ValidationError

        owner_a, owner_b = self.user_ids
        org_a, org_b = self.organization_ids[owner_a], self.organization_ids[owner_b]
        first_payload = self._payload(org_a)
        initial = await self._submit(first_payload, owner_a, "request-001")

        async with self.sessions() as session:
            persisted = [
                await session.scalar(select(func.count()).select_from(model))
                for model in (Meeting, Transcript, ProcessingJobRecord, MeetingSubmissionIdempotency, JobOutboxEvent)
            ]
            self.assertEqual(persisted, [1, 1, 1, 1, 1])
            outbox = await session.scalar(select(JobOutboxEvent))
            self.assertEqual(outbox.status, "pending")
            self.assertEqual(outbox.payload["transcript_id"], str(initial.transcript_id))
            first_job_id = outbox.job_id
            job = await session.get(ProcessingJobRecord, outbox.job_id)
            self.assertIsNotNone(job)
            self.assertEqual(outbox.job_id, job.job_id)
            self.assertEqual(job.owner_id, owner_a)

        replay = await self._submit(first_payload, owner_a, "request-001")
        self.assertEqual(replay, initial)
        with self.assertRaises(ConflictError):
            await self._submit(self._payload(org_a, "Changed title"), owner_a, "request-001")

        owner_b_same_key = await self._submit(self._payload(org_b), owner_b, "request-001")
        self.assertNotEqual(owner_b_same_key.meeting_id, initial.meeting_id)
        with self.assertRaises(ForbiddenError):
            await self._submit(self._payload(org_b), owner_a, "not-a-member")

        async with self.sessions() as session:
            before_failed = [
                await session.scalar(select(func.count()).select_from(model))
                for model in (Meeting, Transcript, ProcessingJobRecord, MeetingSubmissionIdempotency, JobOutboxEvent)
            ]
        malformed = self._payload(org_a)
        malformed = malformed.model_copy(
            update={"transcript": malformed.transcript.model_copy(update={"segments": []})}
        )
        with self.assertRaises(ValidationError):
            await self._submit(malformed, owner_a, "rolled-back")
        async with self.sessions() as session:
            after_failed = [
                await session.scalar(select(func.count()).select_from(model))
                for model in (Meeting, Transcript, ProcessingJobRecord, MeetingSubmissionIdempotency, JobOutboxEvent)
            ]
            self.assertEqual(after_failed, before_failed)
            self.assertIsNone(
                await session.scalar(
                    select(MeetingSubmissionIdempotency).where(
                        MeetingSubmissionIdempotency.owner_id == owner_a,
                        MeetingSubmissionIdempotency.idempotency_key == "rolled-back",
                    )
                )
            )
            self.assertEqual(
                await session.scalar(
                    select(func.count()).select_from(JobOutboxEvent).where(
                        JobOutboxEvent.job_id == first_job_id
                    )
                ),
                1,
            )

        # Later edits append; the original job retains its exact transcript ID/text.
        from app.repositories.meeting_repository import MeetingRepository
        from app.repositories.transcript_repository import TranscriptRepository
        from app.services.meeting_service import MeetingService
        from shared.schemas.transcript import TranscriptSegment

        async with self.sessions() as session:
            service = MeetingService(session, MeetingRepository(session), TranscriptRepository(session))
            await service.replace_transcript(
                str(initial.meeting_id),
                segments=[TranscriptSegment(index=0, text="Revised transcript.")],
                language="en",
                authenticated_user_id=owner_a,
            )
        async with self.sessions() as session:
            revisions = list(
                (
                    await session.scalars(
                        select(Transcript).where(Transcript.meeting_id == initial.meeting_id)
                        .order_by(Transcript.revision_number)
                    )
                ).all()
            )
            self.assertEqual([row.revision_number for row in revisions], [1, 2])
            self.assertEqual(revisions[0].segments[0]["text"], "Review the launch plan.")
            processing_job = await session.get(ProcessingJobRecord, first_job_id)
            self.assertEqual(processing_job.transcript_id, revisions[0].id)

        # Separate DB sessions racing on an identical owner/key converge on one receipt.
        concurrent_payload = self._payload(org_a, "Concurrent submission")
        concurrent = await asyncio.gather(
            self._submit(concurrent_payload, owner_a, "concurrent-001"),
            self._submit(concurrent_payload, owner_a, "concurrent-001"),
        )
        self.assertEqual(concurrent[0], concurrent[1])
        async with self.sessions() as session:
            matching_meeting = await session.get(Meeting, concurrent[0].meeting_id)
            self.assertIsNotNone(matching_meeting)
            self.assertEqual(matching_meeting.title, "Concurrent submission")
            for model in (Transcript, ProcessingJobRecord):
                self.assertEqual(
                    await session.scalar(
                        select(func.count()).select_from(model).where(
                            model.meeting_id == concurrent[0].meeting_id
                        )
                    ),
                    1,
                )
            idem = await session.scalar(
                select(MeetingSubmissionIdempotency).where(
                    MeetingSubmissionIdempotency.owner_id == owner_a,
                    MeetingSubmissionIdempotency.idempotency_key == "concurrent-001",
                )
            )
            self.assertIsNotNone(idem)
            self.assertEqual(
                await session.scalar(
                    select(func.count()).select_from(JobOutboxEvent).where(
                        JobOutboxEvent.job_id == idem.job_id
                    )
                ),
                1,
            )

    async def test_outbox_claim_is_bounded_eligible_and_concurrency_safe(self) -> None:
        from sqlalchemy import select

        from app.repositories.job_outbox_repository import JobOutboxRepository
        from shared.database.models.job_outbox_event import JobOutboxEvent
        from shared.jobs.outbox_policy import OutboxFailureCategory

        owner_id = self.user_ids[0]
        organization_id = self.organization_ids[owner_id]
        submissions = [
            await self._submit(self._payload(organization_id, f"Claim case {index}"), owner_id, f"claim-{index}")
            for index in range(7)
        ]
        event_by_meeting = {}
        async with self.sessions() as session:
            for submission in submissions:
                event = await session.scalar(
                    select(JobOutboxEvent).where(
                        JobOutboxEvent.payload["meeting_id"].as_string() == str(submission.meeting_id)
                    )
                )
                self.assertIsNotNone(event)
                event_by_meeting[submission.meeting_id] = event

        now = datetime.now(timezone.utc)
        active_token = uuid.uuid4()
        future_event = event_by_meeting[submissions[2].meeting_id]
        published_event = event_by_meeting[submissions[3].meeting_id]
        active_event = event_by_meeting[submissions[4].meeting_id]
        deferred_concurrent_events = {
            event_by_meeting[submissions[index].meeting_id].id for index in (5, 6)
        }
        eligible_ids = {
            event_by_meeting[submissions[index].meeting_id].id for index in (0, 1)
        }
        async with self.sessions() as session:
            future_row = await session.get(JobOutboxEvent, future_event.id)
            future_row.available_at = now + timedelta(hours=1)
            published_row = await session.get(JobOutboxEvent, published_event.id)
            published_row.status = "published"
            published_row.published_at = now
            active_row = await session.get(JobOutboxEvent, active_event.id)
            active_row.lock_token = active_token
            active_row.locked_until = now + timedelta(hours=1)
            for event_id in eligible_ids:
                row = await session.get(JobOutboxEvent, event_id)
                row.available_at = now - timedelta(seconds=1)
            for event_id in deferred_concurrent_events:
                row = await session.get(JobOutboxEvent, event_id)
                row.available_at = now + timedelta(hours=1)
            await session.commit()

        async def claim_once(token):
            async with self.sessions() as session:
                async with session.begin():
                    return await JobOutboxRepository(session).claim_next(
                        now=now,
                        lease_token=token,
                        locked_until=now + timedelta(minutes=2),
                    )

        first = await claim_once(uuid.uuid4())
        second = await claim_once(uuid.uuid4())
        self.assertIn(first.id, eligible_ids)
        self.assertIn(second.id, eligible_ids)
        self.assertNotEqual(first.id, second.id)
        self.assertIsNotNone(first.lock_token)
        self.assertIsNotNone(first.locked_until)
        self.assertEqual(first.status, "pending")
        self.assertIsNotNone(second.lock_token)
        async with self.sessions() as session:
            for claimed in (first, second):
                persisted = await session.get(JobOutboxEvent, claimed.id)
                self.assertEqual(persisted.lock_token, claimed.lock_token)
                self.assertEqual(persisted.locked_until, now + timedelta(minutes=2))

        from app.repositories.job_outbox_repository import JobOutboxRepository

        async with self.sessions() as session:
            async with session.begin():
                wrong_token_ack = await JobOutboxRepository(session).acknowledge_published(
                    first.id, uuid.uuid4(), published_at=now
                )
                self.assertFalse(wrong_token_ack)
        async with self.sessions() as session:
            async with session.begin():
                correct_ack = await JobOutboxRepository(session).acknowledge_published(
                    first.id, first.lock_token, published_at=now
                )
                self.assertTrue(correct_ack)
                stale_ack = await JobOutboxRepository(session).acknowledge_published(
                    first.id, first.lock_token, published_at=now
                )
                self.assertFalse(stale_ack)
        async with self.sessions() as session:
            acknowledged_row = await session.get(JobOutboxEvent, first.id)
            self.assertEqual(acknowledged_row.status, "published")
            self.assertEqual(acknowledged_row.published_at, now)
            self.assertIsNone(acknowledged_row.lock_token)
            self.assertIsNone(acknowledged_row.locked_until)

        # The only remaining rows are future-dated, published, or under an
        # unexpired lease. None may be changed or returned by a claim.
        self.assertIsNone(await claim_once(uuid.uuid4()))
        async with self.sessions() as session:
            future_after = await session.get(JobOutboxEvent, future_event.id)
            published_after = await session.get(JobOutboxEvent, published_event.id)
            active_after = await session.get(JobOutboxEvent, active_event.id)
            self.assertEqual(future_after.available_at, now + timedelta(hours=1))
            self.assertEqual(future_after.attempt_count, 0)
            self.assertEqual((published_after.status, published_after.published_at), ("published", now))
            self.assertEqual(published_after.attempt_count, 0)
            self.assertEqual((active_after.lock_token, active_after.locked_until), (active_token, now + timedelta(hours=1)))
            self.assertEqual(active_after.attempt_count, 0)
            for event_id in deferred_concurrent_events:
                deferred = await session.get(JobOutboxEvent, event_id)
                self.assertEqual(deferred.available_at, now + timedelta(hours=1))
                self.assertEqual(deferred.attempt_count, 0)

        # Two independent transactions can claim two different rows at once;
        # row locks and persisted lease fields prevent duplicate assignment.
        concurrent_ids = deferred_concurrent_events
        async with self.sessions() as session:
            for event_id in concurrent_ids:
                row = await session.get(JobOutboxEvent, event_id)
                row.available_at = now - timedelta(seconds=1)
            await session.commit()
        concurrent = await asyncio.gather(
            claim_once(uuid.uuid4()),
            claim_once(uuid.uuid4()),
        )
        self.assertTrue(all(event is not None for event in concurrent))
        self.assertEqual({event.id for event in concurrent}, concurrent_ids)
        self.assertEqual({event.attempt_count for event in concurrent}, {1})

    async def test_outbox_retry_backoff_permanent_stop_and_crash_exhaustion(self) -> None:
        from sqlalchemy import select

        from app.repositories.job_outbox_repository import JobOutboxRepository
        from shared.database.models.job_outbox_event import JobOutboxEvent
        from shared.jobs.outbox_policy import OutboxFailureCategory

        owner_id = self.user_ids[0]
        organization_id = self.organization_ids[owner_id]
        retry_receipt = await self._submit(
            self._payload(organization_id, "Outbox retry semantics"),
            owner_id,
            "outbox-retry-semantics",
        )
        async with self.sessions() as session:
            retry_event = await session.scalar(
                select(JobOutboxEvent).where(
                    JobOutboxEvent.payload["meeting_id"].as_string()
                    == str(retry_receipt.meeting_id)
                )
            )
        self.assertIsNotNone(retry_event)
        retry_job_id = retry_event.job_id

        now = datetime.now(timezone.utc)
        first_token = uuid.uuid4()
        async with self.sessions() as session:
            async with session.begin():
                claimed = await JobOutboxRepository(session).claim_next(
                    now=now,
                    lease_token=first_token,
                    locked_until=now + timedelta(minutes=2),
                    max_attempts=3,
                )
                self.assertEqual(claimed.id, retry_event.id)
                self.assertEqual(claimed.attempt_count, 1)
        async with self.sessions() as session:
            async with session.begin():
                repository = JobOutboxRepository(session)
                stale_recorded = await repository.record_failure(
                    retry_event.id,
                    uuid.uuid4(),
                    category=OutboxFailureCategory.BROKER_UNAVAILABLE,
                    failed_at=now,
                    max_attempts=3,
                    retry_base_seconds=2,
                    retry_max_seconds=60,
                )
                self.assertFalse(stale_recorded)
                recorded = await repository.record_failure(
                    retry_event.id,
                    first_token,
                    category=OutboxFailureCategory.BROKER_UNAVAILABLE,
                    failed_at=now,
                    max_attempts=3,
                    retry_base_seconds=2,
                    retry_max_seconds=60,
                )
                self.assertTrue(recorded)
        async with self.sessions() as session:
            retried = await session.get(JobOutboxEvent, retry_event.id)
            self.assertEqual(retried.job_id, retry_job_id)
            self.assertEqual(retried.attempt_count, 1)
            self.assertEqual(retried.available_at, now + timedelta(seconds=2))
            self.assertEqual(retried.last_error_category, "broker_unavailable")
            self.assertIsNone(retried.lock_token)
        async with self.sessions() as session:
            async with session.begin():
                self.assertIsNone(await JobOutboxRepository(session).claim_next(
                    now=now + timedelta(seconds=1),
                    lease_token=uuid.uuid4(),
                    locked_until=now + timedelta(minutes=3),
                    max_attempts=3,
                ))
        second_token = uuid.uuid4()
        async with self.sessions() as session:
            async with session.begin():
                claimed_again = await JobOutboxRepository(session).claim_next(
                    now=now + timedelta(seconds=2),
                    lease_token=second_token,
                    locked_until=now + timedelta(minutes=4),
                    max_attempts=3,
                )
                self.assertEqual(claimed_again.id, retry_event.id)
                self.assertEqual(claimed_again.job_id, retry_job_id)
                self.assertEqual(claimed_again.attempt_count, 2)
                permanent = await JobOutboxRepository(session).record_failure(
                    retry_event.id,
                    second_token,
                    category=OutboxFailureCategory.AUTHENTICATION_REJECTED,
                    failed_at=now + timedelta(seconds=2),
                    max_attempts=3,
                    retry_base_seconds=2,
                    retry_max_seconds=60,
                )
                self.assertTrue(permanent)
        async with self.sessions() as session:
            stopped = await session.get(JobOutboxEvent, retry_event.id)
            self.assertEqual(stopped.status, "pending")
            self.assertEqual(stopped.last_error_category, "authentication_rejected")
            self.assertIsNone(stopped.lock_token)
        async with self.sessions() as session:
            async with session.begin():
                self.assertIsNone(await JobOutboxRepository(session).claim_next(
                    now=now + timedelta(days=1),
                    lease_token=uuid.uuid4(),
                    locked_until=now + timedelta(days=2),
                    max_attempts=3,
                ))

        crashed_receipt = await self._submit(
            self._payload(organization_id, "Outbox final lease crash"),
            owner_id,
            "outbox-final-lease-crash",
        )
        async with self.sessions() as session:
            crashed = await session.scalar(
                select(JobOutboxEvent).where(
                    JobOutboxEvent.payload["meeting_id"].as_string()
                    == str(crashed_receipt.meeting_id)
                )
            )
        self.assertIsNotNone(crashed)
        crashed_job_id = crashed.job_id
        expired_token = uuid.uuid4()
        async with self.sessions() as session:
            async with session.begin():
                row = await session.get(JobOutboxEvent, crashed.id)
                row.attempt_count = 3
                row.available_at = now - timedelta(seconds=1)
                row.lock_token = expired_token
                row.locked_until = now - timedelta(seconds=1)
                row.last_error_category = "broker_unavailable"
                row.last_error_message = "The publication broker is temporarily unavailable."
        async with self.sessions() as session:
            async with session.begin():
                exhausted = await JobOutboxRepository(session).mark_expired_exhausted(
                    now=now, max_attempts=3
                )
                self.assertEqual(exhausted.id, crashed.id)
        async with self.sessions() as session:
            persisted = await session.get(JobOutboxEvent, crashed.id)
            self.assertEqual(persisted.job_id, crashed_job_id)
            self.assertEqual(persisted.status, "pending")
            self.assertEqual(persisted.last_error_category, "attempts_exhausted")
            self.assertEqual(persisted.last_error_message, "Publication attempts were exhausted.")
            self.assertIsNone(persisted.lock_token)
            self.assertIsNone(persisted.locked_until)

    async def test_ambiguous_outcome_gets_one_separate_recovery_claim(self) -> None:
        from sqlalchemy import select

        from app.repositories.job_outbox_repository import JobOutboxRepository
        from shared.database.models.job_outbox_event import JobOutboxEvent
        from shared.jobs.outbox_policy import OutboxFailureCategory

        owner_id = self.user_ids[0]
        organization_id = self.organization_ids[owner_id]
        receipt = await self._submit(
            self._payload(organization_id, "Ambiguous publication recovery"),
            owner_id,
            "outbox-ambiguous-recovery",
        )
        async with self.sessions() as session:
            event = await session.scalar(
                select(JobOutboxEvent).where(
                    JobOutboxEvent.payload["meeting_id"].as_string() == str(receipt.meeting_id)
                )
            )
        self.assertIsNotNone(event)
        expected_job_id = event.job_id

        now = datetime.now(timezone.utc)
        first_token = uuid.uuid4()
        async with self.sessions() as session:
            async with session.begin():
                claimed = await JobOutboxRepository(session).claim_next(
                    now=now,
                    lease_token=first_token,
                    locked_until=now + timedelta(minutes=2),
                    max_attempts=3,
                )
                self.assertEqual(claimed.id, event.id)
                self.assertEqual(claimed.attempt_count, 1)
                self.assertEqual(claimed.ambiguity_recovery_count, 0)
                self.assertEqual(claimed.last_error_category, "publication_outcome_unknown")

        # A separate committed read establishes that the marker is durable
        # before any external publication call could begin.
        async with self.sessions() as session:
            persisted = await session.get(JobOutboxEvent, event.id)
            self.assertEqual(persisted.last_error_category, "publication_outcome_unknown")
            self.assertEqual(persisted.attempt_count, 1)
            self.assertEqual(persisted.ambiguity_recovery_count, 0)

        recovery_time = now + timedelta(minutes=3)
        recovery_token = uuid.uuid4()
        async with self.sessions() as session:
            async with session.begin():
                repository = JobOutboxRepository(session)
                stale_failure = await repository.record_failure(
                    event.id,
                    first_token,
                    category=OutboxFailureCategory.BROKER_UNAVAILABLE,
                    failed_at=recovery_time,
                    max_attempts=3,
                    retry_base_seconds=2,
                    retry_max_seconds=60,
                )
                stale_ack = await repository.acknowledge_published(
                    event.id, first_token, published_at=recovery_time
                )
                self.assertFalse(stale_failure)
                self.assertFalse(stale_ack)
                recovered = await repository.claim_ambiguous_recovery(
                    now=recovery_time,
                    lease_token=recovery_token,
                    locked_until=recovery_time + timedelta(minutes=2),
                    max_ambiguity_claims=1,
                )
                self.assertEqual(recovered.id, event.id)
                self.assertEqual(recovered.job_id, expected_job_id)
                self.assertEqual(recovered.id, event.id)
                self.assertEqual(recovered.attempt_count, 1)
                self.assertEqual(recovered.ambiguity_recovery_count, 1)
                self.assertEqual(recovered.lock_token, recovery_token)

        # Simulate another crash after the possible broker acceptance. The
        # extra allowance is now spent, so the event stops visibly.
        exhausted_at = recovery_time + timedelta(minutes=3)
        async with self.sessions() as session:
            async with session.begin():
                exhausted = await JobOutboxRepository(session).mark_ambiguous_exhausted(
                    now=exhausted_at,
                    max_ambiguity_claims=1,
                )
                self.assertEqual(exhausted.id, event.id)
        async with self.sessions() as session:
            stopped = await session.get(JobOutboxEvent, event.id)
            self.assertEqual(stopped.job_id, expected_job_id)
            self.assertEqual(stopped.status, "pending")
            self.assertEqual(stopped.attempt_count, 1)
            self.assertEqual(stopped.ambiguity_recovery_count, 1)
            self.assertEqual(stopped.last_error_category, "ambiguous_recovery_exhausted")
            self.assertIsNone(stopped.lock_token)
            self.assertIsNone(stopped.locked_until)

    async def test_one_shot_runtime_commits_one_claim_before_relay(self) -> None:
        from sqlalchemy import select

        from app.services.job_outbox_runtime import OneShotOutboxRuntime, OneShotOutboxStatus
        from shared.database.models.job_outbox_event import JobOutboxEvent

        owner_id = self.user_ids[0]
        organization_id = self.organization_ids[owner_id]
        submissions = [
            await self._submit(self._payload(organization_id, f"Runtime case {index}"), owner_id, f"runtime-{index}")
            for index in range(2)
        ]
        events_by_meeting = {}
        async with self.sessions() as session:
            for submission in submissions:
                event = await session.scalar(
                    select(JobOutboxEvent).where(
                        JobOutboxEvent.payload["meeting_id"].as_string() == str(submission.meeting_id)
                    )
                )
                self.assertIsNotNone(event)
                events_by_meeting[submission.meeting_id] = event

        now = datetime.now(timezone.utc)
        calls = []

        class ObservingRelay:
            async def publish_claimed(_self, event):
                async with self.sessions() as session:
                    persisted = await session.get(JobOutboxEvent, event.id)
                    self.assertIsNotNone(persisted)
                    self.assertEqual(persisted.lock_token, event.lock_token)
                    self.assertEqual(persisted.locked_until, event.locked_until)
                calls.append(event)
                return event.id

        runtime = OneShotOutboxRuntime(
            session_factory=self.sessions,
            relay=ObservingRelay(),
            clock=lambda: now,
        )
        result = await runtime.run_once(locked_until=now + timedelta(minutes=2))

        self.assertEqual(result.status, OneShotOutboxStatus.PUBLISHED)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.event_id, calls[0].id)
        async with self.sessions() as session:
            for submission in submissions:
                persisted = await session.scalar(
                    select(JobOutboxEvent).where(
                        JobOutboxEvent.payload["meeting_id"].as_string() == str(submission.meeting_id)
                    )
                )
                if persisted.id == result.event_id:
                    self.assertIsNotNone(persisted.lock_token)
                    self.assertEqual(persisted.locked_until, now + timedelta(minutes=2))
                else:
                    self.assertIsNone(persisted.lock_token)
                    self.assertIsNone(persisted.locked_until)


if __name__ == "__main__":
    unittest.main()
