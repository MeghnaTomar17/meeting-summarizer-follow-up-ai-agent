"""Opt-in PostgreSQL integration checks for persisted meeting-domain results."""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MEETING_ROOT = BACKEND_ROOT / "meeting-service"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@unittest.skipUnless(
    os.environ.get("RUN_POSTGRES_INTEGRATION") == "1",
    "Set RUN_POSTGRES_INTEGRATION=1 to run PostgreSQL integration tests",
)
class Phase5PostgresIntegrationTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        for key in list(sys.modules):
            if key == "app" or key.startswith("app."):
                del sys.modules[key]
        while str(MEETING_ROOT) in sys.path:
            sys.path.remove(str(MEETING_ROOT))
        sys.path.insert(0, str(MEETING_ROOT))
        from shared.config.base import get_base_settings
        from shared.database.session import get_session_factory, init_database

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
        self.owner_id = uuid.uuid4()
        self.assignee_id = uuid.uuid4()
        self.meeting_id = uuid.uuid4()

    async def asyncTearDown(self) -> None:
        from shared.database.models.meeting import Meeting
        from shared.database.models.user import User
        from shared.database.session import close_database

        try:
            async with self.session_factory() as session:
                await session.execute(delete(Meeting).where(Meeting.id == self.meeting_id))
                await session.execute(delete(User).where(User.id.in_([self.owner_id, self.assignee_id])))
                await session.commit()
        finally:
            await close_database()

    async def test_phase5_persistence_constraints_filters_and_cascades(self) -> None:
        from shared.database.models.decision import Decision
        from shared.database.models.followup import Followup, FollowupStatus
        from shared.database.models.meeting import Meeting
        from shared.database.models.summary import Summary
        from shared.database.models.task import Task, TaskStatus
        from shared.database.models.transcript import Transcript
        from shared.database.models.user import User
        from app.repositories.decision_repository import DecisionRepository
        from app.repositories.followup_repository import FollowupRepository
        from app.repositories.summary_repository import SummaryRepository
        from app.repositories.task_repository import TaskRepository
        from app.repositories.meeting_repository import MeetingRepository
        from app.repositories.transcript_repository import TranscriptRepository
        from app.services.meeting_service import MeetingService
        from app.services.summary_service import SummaryService
        from shared.exceptions.common import ConflictError
        from shared.schemas.summary import SummaryBase

        async with self.session_factory() as session:
            owner = User(id=self.owner_id, email=f"owner-{self.owner_id}@example.test", password_hash="integration-hash")
            assignee = User(id=self.assignee_id, email=f"assignee-{self.assignee_id}@example.test", password_hash="integration-hash")
            meeting = Meeting(
                id=self.meeting_id,
                organization_id=uuid.uuid4(),
                created_by=self.owner_id,
                title="Phase 5 integration",
                participants=[],
            )
            summary_v1 = Summary(meeting_id=self.meeting_id, content="Version one", key_topics=["one"], version=1)
            summary_v2 = Summary(meeting_id=self.meeting_id, content="Version two", key_topics=["two"], version=2)
            task = Task(meeting_id=self.meeting_id, title="Action", assignee_id=self.assignee_id, status=TaskStatus.OPEN)
            decision = Decision(meeting_id=self.meeting_id, statement="Proceed", participants=[])
            followup = Followup(
                meeting_id=self.meeting_id,
                subject="Next steps",
                body_html="<p>Next</p>",
                recipients=["recipient@example.test"],
                status=FollowupStatus.SCHEDULED,
            )
            transcript = Transcript(meeting_id=self.meeting_id, segments=[{"index": 0, "text": "Proceed"}], language="en")
            session.add_all([owner, assignee, meeting, summary_v1, summary_v2, task, decision, followup, transcript])
            await session.commit()

            summaries = SummaryRepository(session)
            self.assertEqual([item.version for item in await summaries.list_by_meeting_id(self.meeting_id)], [1, 2])
            self.assertEqual((await summaries.get_latest_by_meeting_id(self.meeting_id)).version, 2)
            tasks = TaskRepository(session)
            self.assertEqual(len(await tasks.list_by_meeting_id(self.meeting_id, status=TaskStatus.OPEN)), 1)
            self.assertEqual(len(await DecisionRepository(session).list_by_meeting_id(self.meeting_id)), 1)
            followups = FollowupRepository(session)
            self.assertEqual(len(await followups.list_by_meeting_id(self.meeting_id, status=FollowupStatus.SCHEDULED)), 1)
            self.assertIsNotNone(await session.get(Transcript, transcript.id))

        async with self.session_factory() as session:
            session.add(Summary(meeting_id=self.meeting_id, content="Duplicate", key_topics=[], version=1))
            with self.assertRaises(IntegrityError):
                await session.flush()
            await session.rollback()

        async with self.session_factory() as session:
            meeting_service = MeetingService(
                session,
                MeetingRepository(session),
                TranscriptRepository(session),
            )
            summary_service = SummaryService(
                session,
                SummaryRepository(session),
                meeting_service,
            )
            with self.assertRaises(ConflictError):
                await summary_service.create_summary(
                    SummaryBase(meeting_id=str(self.meeting_id), content="Duplicate", key_topics=[]),
                    self.owner_id,
                    version=1,
                )

        async with self.session_factory() as session:
            await session.execute(delete(User).where(User.id == self.assignee_id))
            await session.commit()
            task_after_assignee_delete = await session.get(Task, task.id)
            self.assertIsNotNone(task_after_assignee_delete)
            self.assertIsNone(task_after_assignee_delete.assignee_id)

            # A SQL DELETE exercises the database ON DELETE CASCADE constraints.
            await session.execute(delete(Meeting).where(Meeting.id == self.meeting_id))
            await session.commit()
            for model in (Transcript, Summary, Task, Decision, Followup):
                result = await session.execute(select(model).where(model.meeting_id == self.meeting_id))
                self.assertEqual(result.scalars().all(), [], model.__tablename__)


if __name__ == "__main__":
    unittest.main()
