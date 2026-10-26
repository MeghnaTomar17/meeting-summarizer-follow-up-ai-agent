"""Owner-scoped analytics repository and deterministic service tests."""

from __future__ import annotations

import asyncio
import importlib
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MEETING_ROOT = BACKEND_ROOT / "meeting-service"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _prepare_meeting_imports() -> None:
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    while str(MEETING_ROOT) in sys.path:
        sys.path.remove(str(MEETING_ROOT))
    sys.path.insert(0, str(MEETING_ROOT))


class _Result:
    def __init__(self, *, scalar=None, rows=()):
        self._scalar = scalar
        self._rows = list(rows)

    def scalar_one(self):
        return self._scalar

    def all(self):
        return self._rows


class AnalyticsServiceTests(unittest.TestCase):
    def setUp(self):
        _prepare_meeting_imports()

    def test_week_range_is_utc_bounded_and_zero_weeks_are_included(self):
        service_type = importlib.import_module("app.services.analytics_service").AnalyticsService
        now = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
        repository = SimpleNamespace(
            get_overview=AsyncMock(return_value={
                "total_meetings": 4,
                "weekly_rows": [(datetime(2026, 10, 12), 2)],
                "task_counts": {},
                "overdue_tasks": 0,
                "decisions": 0,
                "followup_counts": {},
                "meeting_status_counts": {},
                "processing_job_status_counts": {},
            })
        )
        result = asyncio.run(service_type(repository, clock=lambda: now).overview(uuid.uuid4(), weeks=3))
        self.assertEqual(
            [item.week_start.isoformat() for item in result.meetings_per_week],
            ["2026-10-05", "2026-10-12", "2026-10-19"],
        )
        self.assertEqual([item.count for item in result.meetings_per_week], [0, 2, 0])
        call = repository.get_overview.await_args
        self.assertEqual(call.kwargs["week_start"], datetime(2026, 10, 5, tzinfo=timezone.utc))
        self.assertEqual(call.kwargs["week_end"], datetime(2026, 10, 26, tzinfo=timezone.utc))
        self.assertEqual(call.kwargs["as_of"], now)

    def test_metrics_use_actual_status_sets_and_include_zero_statuses(self):
        service_type = importlib.import_module("app.services.analytics_service").AnalyticsService
        from shared.jobs.lifecycle import JobStatus
        from shared.schemas.followup import FollowupStatus
        from shared.schemas.meeting import MeetingStatus
        from shared.schemas.task import TaskStatus

        repository = SimpleNamespace(
            get_overview=AsyncMock(return_value={
                "total_meetings": 2,
                "weekly_rows": [],
                "task_counts": {TaskStatus.OPEN: 2, TaskStatus.IN_PROGRESS: 1, TaskStatus.DONE: 3},
                "overdue_tasks": 1,
                "decisions": 4,
                "followup_counts": {FollowupStatus.SENT: 2, FollowupStatus.DRAFT: 1},
                "meeting_status_counts": {MeetingStatus.READY: 2},
                "processing_job_status_counts": {JobStatus.FAILED: 1},
            })
        )
        result = asyncio.run(service_type(repository).overview(uuid.uuid4(), weeks=1))
        self.assertEqual((result.open_tasks, result.completed_tasks, result.overdue_tasks), (3, 3, 1))
        self.assertEqual((result.decisions, result.followups), (4, 3))
        self.assertEqual(sum(result.followup_status_counts.values()), result.followups)
        self.assertEqual(result.meeting_status_counts[MeetingStatus.READY], 2)
        self.assertEqual(result.meeting_status_counts[MeetingStatus.FAILED], 0)
        self.assertEqual(result.processing_job_status_counts[JobStatus.FAILED], 1)
        self.assertEqual(result.processing_job_status_counts[JobStatus.QUEUED], 0)
        self.assertEqual(len(result.meetings_per_week), 1)

    def test_rejects_invalid_week_bounds_and_naive_clock(self):
        service_type = importlib.import_module("app.services.analytics_service").AnalyticsService
        repository = SimpleNamespace(get_overview=AsyncMock())
        service = service_type(repository, clock=lambda: datetime(2026, 1, 1))
        for weeks in (0, 53, True):
            with self.subTest(weeks=weeks), self.assertRaises(ValueError):
                asyncio.run(service.overview(uuid.uuid4(), weeks=weeks))
        with self.assertRaises(ValueError):
            asyncio.run(service.overview(uuid.uuid4(), weeks=1))
        repository.get_overview.assert_not_awaited()

    def test_repository_uses_separate_owner_scoped_aggregates_without_fanout(self):
        _prepare_meeting_imports()
        from app.repositories.analytics_repository import AnalyticsRepository
        from shared.database.models.followup import FollowupStatus as OrmFollowupStatus
        from shared.database.models.meeting import MeetingStatus as OrmMeetingStatus
        from shared.database.models.task import TaskStatus as OrmTaskStatus
        from shared.jobs.lifecycle import JobStatus

        owner_id = uuid.uuid4()
        session = SimpleNamespace(execute=AsyncMock(side_effect=[
            _Result(scalar=2),
            _Result(rows=[(datetime(2026, 10, 12), 1)]),
            _Result(rows=[(OrmTaskStatus.OPEN, 1), (OrmTaskStatus.DONE, 2)]),
            _Result(scalar=0),
            _Result(scalar=3),
            _Result(rows=[(OrmFollowupStatus.SENT, 1)]),
            _Result(rows=[(OrmMeetingStatus.READY, 2)]),
            _Result(rows=[(JobStatus.QUEUED.value, 1)]),
        ]))
        asyncio.run(AnalyticsRepository(session).get_overview(
            owner_id,
            week_start=datetime(2026, 10, 12, tzinfo=timezone.utc),
            week_end=datetime(2026, 10, 19, tzinfo=timezone.utc),
            as_of=datetime(2026, 10, 25, tzinfo=timezone.utc),
        ))

        statements = [call.args[0] for call in session.execute.await_args_list]
        self.assertEqual(len(statements), 8)
        for statement in statements:
            compiled = statement.compile()
            self.assertIn(owner_id, compiled.params.values())
        sql = [str(statement).lower() for statement in statements]
        self.assertIn("timezone", sql[1])
        self.assertIn("join meetings", sql[2])
        self.assertIn("join meetings", sql[3])
        self.assertIn("join meetings", sql[4])
        self.assertIn("join meetings", sql[5])
        self.assertIn("join meetings", sql[7])
        self.assertNotIn("join tasks", sql[0])
        self.assertNotIn("join followups", sql[5])
        self.assertEqual(session.execute.await_count, 8)

    def test_trends_zero_fill_weeks_and_use_deterministic_topic_order(self):
        service_type = importlib.import_module("app.services.analytics_service").AnalyticsService
        now = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
        repository = SimpleNamespace(
            get_trends=AsyncMock(return_value={
                "weekly_meeting_rows": [(datetime(2026, 10, 12), 2)],
                "decision_rows": [(datetime(2026, 10, 5), 1)],
                "topic_rows": [
                    (datetime(2026, 10, 12), "launch plan", 2),
                    (datetime(2026, 10, 12), "vendor risk", 1),
                ],
            })
        )
        service = service_type(repository, clock=lambda: now)
        result = asyncio.run(service.trends(uuid.uuid4(), weeks=3, topics_per_week=4))

        self.assertEqual(
            [point.week_start.isoformat() for point in result.meeting_frequency],
            ["2026-10-05", "2026-10-12", "2026-10-19"],
        )
        self.assertEqual([point.count for point in result.meeting_frequency], [0, 2, 0])
        self.assertEqual([point.count for point in result.decision_trends], [1, 0, 0])
        self.assertEqual(
            [topic.topic for topic in result.topic_trends[1].topics],
            ["launch plan", "vendor risk"],
        )
        self.assertEqual(repository.get_trends.await_args.kwargs["topics_per_week"], 4)
        self.assertEqual(
            repository.get_trends.await_args.kwargs["week_start"],
            datetime(2026, 10, 5, tzinfo=timezone.utc),
        )

    def test_trends_reject_invalid_week_and_topic_limits_before_repository_call(self):
        service_type = importlib.import_module("app.services.analytics_service").AnalyticsService
        repository = SimpleNamespace(get_trends=AsyncMock())
        service = service_type(repository, clock=lambda: datetime(2026, 10, 25, tzinfo=timezone.utc))
        for kwargs in ({"weeks": 0}, {"weeks": 53}, {"topics_per_week": 0}, {"topics_per_week": 26}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                asyncio.run(service.trends(uuid.uuid4(), **kwargs))
        repository.get_trends.assert_not_awaited()

    def test_trends_queries_are_owner_scoped_and_normalize_latest_summary_topics(self):
        _prepare_meeting_imports()
        from app.repositories.analytics_repository import AnalyticsRepository
        from sqlalchemy.dialects import postgresql

        owner_id = uuid.uuid4()
        session = SimpleNamespace(execute=AsyncMock(side_effect=[
            _Result(rows=[]),
            _Result(rows=[]),
            _Result(rows=[]),
        ]))
        asyncio.run(AnalyticsRepository(session).get_trends(
            owner_id,
            week_start=datetime(2026, 10, 12, tzinfo=timezone.utc),
            week_end=datetime(2026, 10, 19, tzinfo=timezone.utc),
            topics_per_week=7,
        ))
        statements = [call.args[0] for call in session.execute.await_args_list]
        self.assertEqual(len(statements), 3)
        compiled = [statement.compile(dialect=postgresql.dialect()) for statement in statements]
        for statement in compiled:
            self.assertIn(owner_id, statement.params.values())

        meeting_frequency_sql = str(compiled[0]).lower()
        decision_sql = str(compiled[1]).lower()
        topic_sql = str(compiled[2]).lower()
        self.assertIn("meetings.scheduled_at", meeting_frequency_sql)
        self.assertIn("timezone", meeting_frequency_sql)
        self.assertIn("decisions.created_at", decision_sql)
        self.assertIn("timezone", decision_sql)
        self.assertIn("decisions.created_at >=", decision_sql)
        self.assertIn("decisions.created_at <", decision_sql)
        self.assertIn("order by date_trunc", decision_sql)
        self.assertIn("meetings.created_by", topic_sql)
        self.assertIn("summaries.version desc", topic_sql)
        self.assertIn("jsonb_typeof", topic_sql)
        self.assertIn("jsonb_array_elements", topic_sql)
        self.assertIn("regexp_replace", topic_sql)
        self.assertIn("distinct", topic_sql)
        self.assertIn("row_number() over", topic_sql)
        self.assertIn("topic_rank", topic_sql)
        self.assertIn("meetings.scheduled_at", topic_sql)
        self.assertIn("meetings.scheduled_at >=", topic_sql)
        self.assertIn("meetings.scheduled_at <", topic_sql)
        self.assertIn("<=", topic_sql)

    def test_recurring_blockers_build_stable_groups_with_original_provenance(self):
        service_type = importlib.import_module("app.services.analytics_service").AnalyticsService
        owner_id = uuid.uuid4()
        meeting_a, meeting_b = uuid.uuid4(), uuid.uuid4()
        insight_a, insight_b = uuid.uuid4(), uuid.uuid4()
        created = datetime(2026, 10, 1, tzinfo=timezone.utc)
        repository = SimpleNamespace(get_recurring_blockers=AsyncMock(return_value=[{
            "normalized_description": "vendor approval is blocking launch",
            "meeting_count": 2,
            "evidence_count": 3,
            "evidence": [
                (meeting_a, insight_a, "Vendor blocker", " Vendor approval is blocking launch ", created),
                (meeting_a, uuid.uuid4(), "Vendor blocker", "vendor approval is blocking launch", created),
                (meeting_b, insight_b, "Launch blocker", "VENDOR APPROVAL IS BLOCKING LAUNCH", created),
            ],
        }]))
        service = service_type(repository)

        first = asyncio.run(service.recurring_blockers(owner_id))
        second = asyncio.run(service.recurring_blockers(owner_id))

        group = first.recurring_blockers[0]
        self.assertEqual(group.group_id, second.recurring_blockers[0].group_id)
        self.assertEqual(group.description, " Vendor approval is blocking launch ")
        self.assertEqual(group.meeting_count, 2)
        self.assertEqual(group.evidence_count, 3)
        self.assertTrue(group.evidence_truncated is False)
        self.assertEqual({item.meeting_id for item in group.evidence}, {meeting_a, meeting_b})
        self.assertEqual({item.insight_id for item in group.evidence} & {insight_a, insight_b}, {insight_a, insight_b})
        repository.get_recurring_blockers.assert_awaited_with(owner_id)

    def test_recurring_blockers_rejects_repository_group_without_two_visible_meetings(self):
        service_type = importlib.import_module("app.services.analytics_service").AnalyticsService
        meeting = uuid.uuid4()
        repository = SimpleNamespace(get_recurring_blockers=AsyncMock(return_value=[{
            "normalized_description": "same blocker",
            "meeting_count": 2,
            "evidence_count": 2,
            "evidence": [
                (meeting, uuid.uuid4(), "Blocker", "same blocker", datetime.now(timezone.utc)),
                (meeting, uuid.uuid4(), "Blocker", "same blocker", datetime.now(timezone.utc)),
            ],
        }]))
        result = asyncio.run(service_type(repository).recurring_blockers(uuid.uuid4()))
        self.assertEqual(result.recurring_blockers, [])

    def test_recurring_blockers_empty_results_and_evidence_truncation(self):
        service_type = importlib.import_module("app.services.analytics_service").AnalyticsService
        empty_repository = SimpleNamespace(
            get_recurring_blockers=AsyncMock(return_value=[])
        )
        empty = asyncio.run(service_type(empty_repository).recurring_blockers(uuid.uuid4()))
        self.assertEqual(empty.recurring_blockers, [])

        references = [
            (uuid.uuid4(), uuid.uuid4(), "Blocker", "same exact blocker", datetime.now(timezone.utc))
            for _ in range(2)
        ]
        truncated_repository = SimpleNamespace(get_recurring_blockers=AsyncMock(return_value=[{
            "normalized_description": "same exact blocker",
            "meeting_count": 103,
            "evidence_count": 103,
            "evidence": references,
        }]))
        result = asyncio.run(
            service_type(truncated_repository).recurring_blockers(uuid.uuid4())
        )
        self.assertTrue(result.recurring_blockers[0].evidence_truncated)
        self.assertEqual(result.recurring_blockers[0].meeting_count, 103)
        self.assertEqual(len(result.recurring_blockers[0].evidence), 2)

    def test_recurring_blockers_query_uses_exact_blocker_category_owner_and_distinct_meetings(self):
        _prepare_meeting_imports()
        from app.repositories.analytics_repository import AnalyticsRepository
        from shared.schemas.meeting_insight import InsightCategory
        from sqlalchemy.dialects import postgresql

        owner_id = uuid.uuid4()
        created = datetime(2026, 10, 1, tzinfo=timezone.utc)
        session = SimpleNamespace(execute=AsyncMock(side_effect=[
            _Result(rows=[("same persisted blocker", 2, 3)]),
            _Result(rows=[
                ("same persisted blocker", uuid.uuid4(), uuid.uuid4(), "Blocker A", " Same persisted blocker ", created),
                ("same persisted blocker", uuid.uuid4(), uuid.uuid4(), "Blocker B", "SAME PERSISTED BLOCKER", created),
            ]),
        ]))
        result = asyncio.run(AnalyticsRepository(session).get_recurring_blockers(owner_id))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["meeting_count"], 2)
        self.assertEqual(result[0]["evidence_count"], 3)
        self.assertEqual(len(result[0]["evidence"]), 2)

        statements = [call.args[0] for call in session.execute.await_args_list]
        sql = [str(statement.compile(dialect=postgresql.dialect())).lower() for statement in statements]
        params = [statement.compile(dialect=postgresql.dialect()).params for statement in statements]
        self.assertTrue(all(owner_id in statement_params.values() for statement_params in params))
        self.assertTrue(all("meeting_insights.category" in statement for statement in sql))
        self.assertTrue(all("meeting_insights.description" in statement for statement in sql))
        self.assertTrue(all("meeting_insights.meeting_id" in statement for statement in sql))
        self.assertIn(InsightCategory.BLOCKER.value, [
            value for statement_params in params for value in statement_params.values()
        ])
        self.assertIn("count(distinct", sql[0])
        self.assertIn(">=", sql[0])
        self.assertIn("regexp_replace", sql[0])
        self.assertIn("group by owned_blocker_insights.normalized_description", sql[0])
        self.assertIn("normalized_description asc", sql[0])
        self.assertIn("limit", sql[0])
        self.assertIn("row_number() over", sql[1])
        self.assertIn("meeting_evidence_rank", sql[1])
        self.assertIn("evidence_rank", sql[1])
        self.assertIn("<=", sql[1])
        self.assertIn("order by", sql[1])

    def test_task_completion_trends_reports_missing_history_without_querying(self):
        service_type = importlib.import_module("app.services.analytics_service").AnalyticsService
        repository = SimpleNamespace()
        result = asyncio.run(service_type(repository).task_completion_trends(uuid.uuid4()))
        self.assertFalse(result.available)
        self.assertIn("no completion timestamp or status-transition history", result.reason)

    def test_speaker_participation_aggregates_speakers_and_unknown_segments(self):
        service_type = importlib.import_module("app.services.analytics_service").AnalyticsService
        meeting_a, transcript_a = uuid.uuid4(), uuid.uuid4()
        meeting_b, transcript_b = uuid.uuid4(), uuid.uuid4()
        repository = SimpleNamespace(get_speaker_participation=AsyncMock(return_value={
            "total_transcripts": 3,
            "rows": [
                (meeting_a, transcript_a, 5, 2, 2, "Alice", 2),
                (meeting_a, transcript_a, 5, 2, 2, "Bob", 1),
                (meeting_b, transcript_b, 0, 0, 0, None, 0),
            ],
        }))
        service = service_type(repository)
        result = asyncio.run(service.speaker_participation(uuid.uuid4(), meetings_limit=2))
        self.assertEqual(result.total_transcripts, 3)
        self.assertTrue(result.truncated)
        self.assertEqual([meeting.meeting_id for meeting in result.meetings], [meeting_a, meeting_b])
        self.assertEqual(result.meetings[0].segment_count, 5)
        self.assertEqual(result.meetings[0].unknown_speaker_segment_count, 2)
        self.assertEqual(
            [(speaker.speaker, speaker.segment_count) for speaker in result.meetings[0].speakers],
            [("Alice", 2), ("Bob", 1)],
        )
        self.assertEqual(result.meetings[1].segment_count, 0)
        self.assertEqual(result.meetings[1].speakers, [])
        self.assertFalse(result.meetings[1].speakers_truncated)
        self.assertEqual(
            repository.get_speaker_participation.await_args.kwargs,
            {"meetings_limit": 2},
        )

    def test_speaker_participation_rejects_invalid_limit_before_query(self):
        service_type = importlib.import_module("app.services.analytics_service").AnalyticsService
        repository = SimpleNamespace(get_speaker_participation=AsyncMock())
        service = service_type(repository)
        for limit in (0, 101, True):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                asyncio.run(service.speaker_participation(uuid.uuid4(), meetings_limit=limit))
        repository.get_speaker_participation.assert_not_awaited()

    def test_speaker_participation_query_is_owner_scoped_deduplicates_and_bounds_results(self):
        _prepare_meeting_imports()
        from app.repositories.analytics_repository import AnalyticsRepository
        from sqlalchemy.dialects import postgresql

        owner_id = uuid.uuid4()
        session = SimpleNamespace(execute=AsyncMock(return_value=_Result(rows=[])))
        result = asyncio.run(
            AnalyticsRepository(session).get_speaker_participation(
                owner_id, meetings_limit=7
            )
        )
        self.assertEqual(result, {"total_transcripts": 0, "rows": []})
        statement = session.execute.await_args.args[0]
        compiled = statement.compile(dialect=postgresql.dialect())
        sql = str(compiled).lower()
        self.assertIn(owner_id, compiled.params.values())
        self.assertIn("meetings.created_by", sql)
        self.assertIn("join transcripts", sql)
        self.assertIn("jsonb_array_elements", sql)
        self.assertIn("with ordinality", sql)
        self.assertIn("row_number() over", sql)
        self.assertIn("duplicate_rank", sql)
        self.assertIn("speaker_rank", sql)
        self.assertTrue(
            any("unknown" in str(value).lower() for value in compiled.params.values())
        )
        self.assertIn("limit", sql)
        self.assertIn("transcripts.segments", sql)


if __name__ == "__main__":
    unittest.main()
