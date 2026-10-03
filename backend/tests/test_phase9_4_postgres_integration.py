"""Opt-in PostgreSQL checks for Phase 9.4 migration and row-lock semantics."""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select

BACKEND_ROOT = Path(__file__).resolve().parents[1]
WORKER_ROOT = BACKEND_ROOT / "worker-service"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKER_ROOT))


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_INTEGRATION") == "1", "Set RUN_POSTGRES_INTEGRATION=1 after applying migrations through head.")
class Phase9_4PostgresIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from shared.config.base import get_base_settings
        from shared.database.session import close_database, get_session_factory, init_database

        self.close_database = close_database
        settings = get_base_settings()
        await init_database(
            settings.database_url,
            pool_size=2,
            max_overflow=0,
            pool_timeout=10,
            pool_recycle=300,
            echo=settings.database_echo,
        )
        self.session_factory = get_session_factory()
        self.owner_id = uuid.uuid4()
        self.meeting_id = uuid.uuid4()
        self.transcript_id = uuid.uuid4()
        self.job_id = uuid.uuid4()
        from shared.database.models.meeting import Meeting
        from shared.database.models.transcript import Transcript
        from shared.database.models.user import User

        async with self.session_factory() as session:
            session.add_all([
                User(id=self.owner_id, email=f"phase94-{self.owner_id}@example.test", password_hash="integration-only"),
                Meeting(id=self.meeting_id, organization_id=uuid.uuid4(), created_by=self.owner_id, title="Phase 9.4 integration", participants=[]),
                Transcript(id=self.transcript_id, meeting_id=self.meeting_id, segments=[{"index": 0, "text": "Review."}], language="en"),
            ])
            await session.commit()

    async def asyncTearDown(self):
        from shared.database.models.meeting import Meeting
        from shared.database.models.user import User

        try:
            async with self.session_factory() as session:
                await session.execute(delete(Meeting).where(Meeting.id == self.meeting_id))
                await session.execute(delete(User).where(User.id == self.owner_id))
                await session.commit()
        finally:
            await self.close_database()

    async def test_migrated_schema_persists_claim_attempt_and_terminal_state(self):
        from shared.database.models.processing_job import ProcessingJobRecord
        from shared.jobs.lifecycle import JobStatus, PostgresJobLifecycle

        settings = get_worker_settings()
        lifecycle = PostgresJobLifecycle(settings)
        try:
            await lifecycle.register(
                job_id=self.job_id,
                meeting_id=self.meeting_id,
                transcript_id=self.transcript_id,
                owner_id=self.owner_id,
                requested_operations=["summary"],
            )
            async with self.session_factory() as session:
                record = (await session.execute(select(ProcessingJobRecord).where(ProcessingJobRecord.job_id == self.job_id))).scalar_one()
                self.assertEqual(record.status, "queued")
                self.assertEqual(record.attempt_count, 0)
                self.assertIsNotNone(record.created_at)

            kwargs = dict(job_id=self.job_id, meeting_id=self.meeting_id, transcript_id=self.transcript_id, owner_id=self.owner_id, requested_operations=["summary"])
            claims = await asyncio.gather(lifecycle.claim(**kwargs), lifecycle.claim(**kwargs))
            self.assertEqual(sum(item.outcome == "claimed" for item in claims), 1)
            self.assertEqual(sum(item.outcome == "already_running" for item in claims), 1)
            claimed = next(item for item in claims if item.outcome == "claimed")
            self.assertEqual(claimed.attempt, 1)
            self.assertTrue(await lifecycle.complete(self.job_id, claimed.lease_token, status=JobStatus.COMPLETED, result={"status": "completed"}))
            terminal = await lifecycle.claim(**kwargs)
            self.assertEqual(terminal.outcome, "terminal")
            async with self.session_factory() as session:
                record = (await session.execute(select(ProcessingJobRecord).where(ProcessingJobRecord.job_id == self.job_id))).scalar_one()
                self.assertEqual(record.status, "completed")
                self.assertEqual(record.attempt_count, 1)
                self.assertIsNotNone(record.completed_at)
        finally:
            await lifecycle.aclose()

    async def test_expired_lease_reclaim_persists_new_fence_and_rejects_stale_worker(self):
        from shared.database.models.processing_job import ProcessingJobRecord
        from shared.jobs.lifecycle import FailureCategory, JobStatus, PostgresJobLifecycle

        lifecycle = PostgresJobLifecycle(get_worker_settings())
        kwargs = dict(
            job_id=self.job_id,
            meeting_id=self.meeting_id,
            transcript_id=self.transcript_id,
            owner_id=self.owner_id,
            requested_operations=["summary"],
        )
        first_claimed_at = datetime.now(timezone.utc)
        try:
            await lifecycle.register(**kwargs)
            first_claim = await lifecycle.claim(**kwargs, now=first_claimed_at)
            self.assertEqual(first_claim.outcome, "claimed")
            self.assertIsNotNone(first_claim.lease_token)

            async with self.session_factory() as session:
                first_record = (
                    await session.execute(
                        select(ProcessingJobRecord).where(ProcessingJobRecord.job_id == self.job_id)
                    )
                ).scalar_one()
                first_lease_expiry = first_record.lease_expires_at
                self.assertEqual(first_record.status, "running")
                self.assertEqual(first_record.attempt_count, 1)
                self.assertEqual(first_record.lease_token, first_claim.lease_token)
                self.assertIsNotNone(first_lease_expiry)

            reclaimed = await lifecycle.claim(
                **kwargs,
                now=first_lease_expiry + timedelta(seconds=1),
            )
            self.assertEqual(reclaimed.outcome, "claimed")
            self.assertEqual(reclaimed.attempt, 2)
            self.assertIsNotNone(reclaimed.lease_token)
            self.assertNotEqual(reclaimed.lease_token, first_claim.lease_token)

            async with self.session_factory() as session:
                reclaimed_record = (
                    await session.execute(
                        select(ProcessingJobRecord).where(ProcessingJobRecord.job_id == self.job_id)
                    )
                ).scalar_one()
                self.assertEqual(reclaimed_record.status, "running")
                self.assertEqual(reclaimed_record.attempt_count, 2)
                self.assertEqual(reclaimed_record.lease_token, reclaimed.lease_token)
                self.assertGreater(reclaimed_record.lease_expires_at, first_lease_expiry)
                self.assertIsNone(reclaimed_record.result)

            self.assertFalse(
                await lifecycle.complete(
                    self.job_id,
                    first_claim.lease_token,
                    status=JobStatus.COMPLETED,
                    result={"worker": "stale"},
                )
            )
            stale_failure = await lifecycle.fail(
                self.job_id,
                first_claim.lease_token,
                category=FailureCategory.TRANSIENT_INFRASTRUCTURE,
                retryable=True,
            )
            self.assertEqual(stale_failure.attempt, 2)

            async with self.session_factory() as session:
                after_stale_actions = (
                    await session.execute(
                        select(ProcessingJobRecord).where(ProcessingJobRecord.job_id == self.job_id)
                    )
                ).scalar_one()
                self.assertEqual(after_stale_actions.status, "running")
                self.assertEqual(after_stale_actions.attempt_count, 2)
                self.assertEqual(after_stale_actions.lease_token, reclaimed.lease_token)
                self.assertIsNone(after_stale_actions.failure_category)
                self.assertIsNone(after_stale_actions.result)

            self.assertTrue(
                await lifecycle.complete(
                    self.job_id,
                    reclaimed.lease_token,
                    status=JobStatus.COMPLETED,
                    result={"worker": "reclaimed"},
                )
            )
            async with self.session_factory() as session:
                final_record = (
                    await session.execute(
                        select(ProcessingJobRecord).where(ProcessingJobRecord.job_id == self.job_id)
                    )
                ).scalar_one()
                self.assertEqual(final_record.status, "completed")
                self.assertEqual(final_record.attempt_count, 2)
                self.assertEqual(final_record.result, {"worker": "reclaimed"})
                self.assertIsNone(final_record.lease_token)
                self.assertIsNone(final_record.lease_expires_at)
        finally:
            await lifecycle.aclose()


def get_worker_settings():
    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            del sys.modules[module_name]
    while str(WORKER_ROOT) in sys.path:
        sys.path.remove(str(WORKER_ROOT))
    sys.path.insert(0, str(WORKER_ROOT))
    from app.config.settings import WorkerSettings

    return WorkerSettings()


if __name__ == "__main__":
    unittest.main()
