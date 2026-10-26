"""Meeting Service analytics route authentication and scope tests."""

from __future__ import annotations

import importlib
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MEETING_ROOT = BACKEND_ROOT / "meeting-service"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _load_app():
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    while str(MEETING_ROOT) in sys.path:
        sys.path.remove(str(MEETING_ROOT))
    sys.path.insert(0, str(MEETING_ROOT))
    main = importlib.import_module("app.main")
    route = importlib.import_module("app.routes.analytics")
    auth = importlib.import_module("app.auth.dependencies")
    return main.app, route, auth


class AnalyticsRouteTests(unittest.TestCase):
    def setUp(self):
        self.app, self.route, self.auth = _load_app()
        self.owner_id = uuid.uuid4()
        self.service = MagicMock()
        self.service.overview = AsyncMock()
        self.service.trends = AsyncMock()
        self.service.recurring_blockers = AsyncMock()
        self.service.task_completion_trends = AsyncMock()
        self.service.speaker_participation = AsyncMock()
        self.app.dependency_overrides[self.route.get_analytics_service] = lambda: self.service
        self.app.dependency_overrides[self.auth.get_authenticated_user_id] = lambda: self.owner_id
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def tearDown(self):
        self.client.close()
        self.app.dependency_overrides.clear()

    def test_internal_route_uses_principal_owner_and_validated_week_count(self):
        from shared.schemas.analytics import AnalyticsOverviewResponse
        from shared.schemas.followup import FollowupStatus
        from shared.schemas.meeting import MeetingStatus
        from shared.jobs.lifecycle import JobStatus

        self.service.overview.return_value = AnalyticsOverviewResponse(
            total_meetings=0, meetings_per_week=[], open_tasks=0, completed_tasks=0,
            overdue_tasks=0, decisions=0, followups=0,
            followup_status_counts={status: 0 for status in FollowupStatus},
            meeting_status_counts={status: 0 for status in MeetingStatus},
            processing_job_status_counts={status: 0 for status in JobStatus},
        )
        response = self.client.get("/analytics/overview?weeks=4&owner_id=" + str(uuid.uuid4()))
        self.assertEqual(response.status_code, 200, response.text)
        self.service.overview.assert_awaited_once_with(self.owner_id, weeks=4)
        self.assertEqual(len(response.json()["meetings_per_week"]), 0)
        self.assertEqual(set(response.json()["meeting_status_counts"]), {s.value for s in MeetingStatus})

        invalid = self.client.get("/analytics/overview?weeks=53")
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(self.service.overview.await_count, 1)

    def test_missing_or_invalid_internal_principal_is_rejected(self):
        self.app.dependency_overrides.pop(self.auth.get_authenticated_user_id)
        self.assertEqual(self.client.get("/analytics/overview").status_code, 401)
        invalid = self.client.get(
            "/analytics/overview", headers={"Authorization": "Bearer invalid-principal"}
        )
        self.assertEqual(invalid.status_code, 401)
        self.service.overview.assert_not_awaited()
        self.service.trends.assert_not_awaited()
        self.service.recurring_blockers.assert_not_awaited()
        self.service.task_completion_trends.assert_not_awaited()
        self.service.speaker_participation.assert_not_awaited()

    def test_trends_route_uses_principal_and_validates_bounded_parameters(self):
        from shared.schemas.analytics import AnalyticsTrendsResponse

        self.service.trends.return_value = AnalyticsTrendsResponse(
            decision_trends=[], meeting_frequency=[], topic_trends=[]
        )
        response = self.client.get(
            "/analytics/trends?weeks=3&topics_per_week=5&owner_id=" + str(uuid.uuid4())
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.service.trends.assert_awaited_once_with(
            self.owner_id, weeks=3, topics_per_week=5
        )
        self.assertEqual(response.json(), {
            "decision_trends": [], "meeting_frequency": [], "topic_trends": []
        })

        invalid_weeks = self.client.get("/analytics/trends?weeks=53")
        invalid_topics = self.client.get("/analytics/trends?topics_per_week=26")
        self.assertEqual(invalid_weeks.status_code, 422)
        self.assertEqual(invalid_topics.status_code, 422)
        self.assertEqual(self.service.trends.await_count, 1)

    def test_recurring_blockers_route_uses_verified_principal_owner(self):
        from shared.schemas.analytics import RecurringBlockersResponse

        self.service.recurring_blockers.return_value = RecurringBlockersResponse(
            recurring_blockers=[]
        )
        response = self.client.get(
            "/analytics/recurring-blockers?owner_id=" + str(uuid.uuid4())
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"recurring_blockers": []})
        self.service.recurring_blockers.assert_awaited_once_with(self.owner_id)

        self.app.dependency_overrides.pop(self.auth.get_authenticated_user_id)
        self.assertEqual(self.client.get("/analytics/recurring-blockers").status_code, 401)

    def test_task_completion_route_exposes_capability_without_accepting_owner_input(self):
        from shared.schemas.analytics import TaskCompletionTrendsResponse

        self.service.task_completion_trends.return_value = TaskCompletionTrendsResponse(
            available=False, reason="No completion timestamp or status history."
        )
        response = self.client.get(
            "/analytics/task-completion-trends?owner_id=" + str(uuid.uuid4())
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["available"])
        self.service.task_completion_trends.assert_awaited_once_with(self.owner_id)

    def test_speaker_participation_route_uses_principal_and_validates_limit(self):
        from shared.schemas.analytics import SpeakerParticipationResponse

        self.service.speaker_participation.return_value = SpeakerParticipationResponse(
            total_transcripts=0, meetings=[], truncated=False
        )
        response = self.client.get(
            "/analytics/speaker-participation?meetings_limit=7&owner_id=" + str(uuid.uuid4())
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.service.speaker_participation.assert_awaited_once_with(
            self.owner_id, meetings_limit=7
        )
        invalid = self.client.get("/analytics/speaker-participation?meetings_limit=101")
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(self.service.speaker_participation.await_count, 1)


if __name__ == "__main__":
    unittest.main()
