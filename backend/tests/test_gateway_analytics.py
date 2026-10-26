"""Authenticated Gateway analytics overview proxy tests."""

from __future__ import annotations

import importlib
import asyncio
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
GATEWAY_ROOT = BACKEND_ROOT / "gateway-service"


def _load_gateway():
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    for service in ("gateway-service", "meeting-service", "ai-service", "search-service"):
        root = str(BACKEND_ROOT / service)
        while root in sys.path:
            sys.path.remove(root)
    sys.path[:0] = [str(GATEWAY_ROOT), str(BACKEND_ROOT)]
    main = importlib.import_module("app.main")
    route = importlib.import_module("app.routes.analytics")
    auth = importlib.import_module("app.auth.dependencies")
    return main.app, route, auth


class GatewayAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.app, self.route, self.auth = _load_gateway()
        from shared.database.models.user import User

        now = datetime.now(timezone.utc)
        self.user = User(
            id=uuid.uuid4(), email="analytics@example.com", password_hash="hash",
            created_at=now, updated_at=now,
        )
        self.meeting_client = MagicMock()
        self.meeting_client.get_analytics_overview = AsyncMock()
        self.meeting_client.get_analytics_trends = AsyncMock()
        self.meeting_client.get_recurring_blockers = AsyncMock()
        self.meeting_client.get_task_completion_trends = AsyncMock()
        self.meeting_client.get_speaker_participation = AsyncMock()
        self.app.dependency_overrides[self.route.get_meeting_client] = lambda: self.meeting_client
        self.app.dependency_overrides[self.auth.get_current_user] = lambda: self.user
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def tearDown(self):
        self.client.close()
        self.app.dependency_overrides.clear()

    def test_overview_route_forwards_owner_weeks_and_request_id(self):
        from shared.schemas.analytics import AnalyticsOverviewResponse
        from shared.schemas.followup import FollowupStatus
        from shared.jobs.lifecycle import JobStatus
        from shared.schemas.meeting import MeetingStatus

        self.meeting_client.get_analytics_overview.return_value = AnalyticsOverviewResponse(
            total_meetings=0, meetings_per_week=[], open_tasks=0, completed_tasks=0,
            overdue_tasks=0, decisions=0, followups=0,
            followup_status_counts={status: 0 for status in FollowupStatus},
            meeting_status_counts={status: 0 for status in MeetingStatus},
            processing_job_status_counts={status: 0 for status in JobStatus},
        )
        response = self.client.get(
            "/api/v1/analytics/overview?weeks=6",
            headers={"X-Request-ID": "analytics-request-1"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.meeting_client.get_analytics_overview.assert_awaited_once_with(
            weeks=6, user_id=self.user.id, request_id="analytics-request-1"
        )

        invalid = self.client.get("/api/v1/analytics/overview?weeks=53")
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(self.meeting_client.get_analytics_overview.await_count, 1)

    def test_unauthenticated_request_does_not_call_meeting_service(self):
        from shared.database.session import get_db_session

        self.app.dependency_overrides.pop(self.auth.get_current_user)
        self.app.dependency_overrides[get_db_session] = lambda: MagicMock()
        response = self.client.get("/api/v1/analytics/overview")
        self.assertEqual(response.status_code, 401)
        self.meeting_client.get_analytics_overview.assert_not_awaited()
        self.meeting_client.get_analytics_trends.assert_not_awaited()
        self.meeting_client.get_recurring_blockers.assert_not_awaited()
        self.meeting_client.get_task_completion_trends.assert_not_awaited()
        self.meeting_client.get_speaker_participation.assert_not_awaited()

    def test_openapi_exposes_mounted_overview_endpoint(self):
        schema = self.app.openapi()
        self.assertIn("/api/v1/analytics/overview", schema["paths"])
        self.assertIn("/api/v1/analytics/trends", schema["paths"])
        self.assertIn("/api/v1/analytics/recurring-blockers", schema["paths"])
        self.assertIn("/api/v1/analytics/task-completion-trends", schema["paths"])
        self.assertIn("/api/v1/analytics/speaker-participation", schema["paths"])

    def test_trends_route_forwards_owner_bounds_and_request_id(self):
        from shared.schemas.analytics import AnalyticsTrendsResponse

        self.meeting_client.get_analytics_trends.return_value = AnalyticsTrendsResponse(
            decision_trends=[], meeting_frequency=[], topic_trends=[]
        )
        response = self.client.get(
            "/api/v1/analytics/trends?weeks=5&topics_per_week=7",
            headers={"X-Request-ID": "analytics-trends-1"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.meeting_client.get_analytics_trends.assert_awaited_once_with(
            weeks=5,
            topics_per_week=7,
            user_id=self.user.id,
            request_id="analytics-trends-1",
        )
        for query in ("weeks=53", "topics_per_week=26"):
            invalid = self.client.get(f"/api/v1/analytics/trends?{query}")
            self.assertEqual(invalid.status_code, 422)
        self.assertEqual(self.meeting_client.get_analytics_trends.await_count, 1)

    def test_recurring_blockers_route_forwards_owner_and_request_id(self):
        from shared.schemas.analytics import RecurringBlockersResponse

        self.meeting_client.get_recurring_blockers.return_value = RecurringBlockersResponse(
            recurring_blockers=[]
        )
        response = self.client.get(
            "/api/v1/analytics/recurring-blockers",
            headers={"X-Request-ID": "analytics-blockers-1"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.meeting_client.get_recurring_blockers.assert_awaited_once_with(
            user_id=self.user.id,
            request_id="analytics-blockers-1",
        )

    def test_task_and_speaker_routes_forward_owner_limits_and_request_ids(self):
        from shared.schemas.analytics import (
            SpeakerParticipationResponse,
            TaskCompletionTrendsResponse,
        )

        self.meeting_client.get_task_completion_trends.return_value = TaskCompletionTrendsResponse(
            available=False, reason="No history."
        )
        self.meeting_client.get_speaker_participation.return_value = SpeakerParticipationResponse(
            total_transcripts=0, meetings=[], truncated=False
        )
        task_response = self.client.get(
            "/api/v1/analytics/task-completion-trends",
            headers={"X-Request-ID": "analytics-task-trends-1"},
        )
        speaker_response = self.client.get(
            "/api/v1/analytics/speaker-participation?meetings_limit=9",
            headers={"X-Request-ID": "analytics-speakers-1"},
        )
        self.assertEqual(task_response.status_code, 200, task_response.text)
        self.assertEqual(speaker_response.status_code, 200, speaker_response.text)
        self.meeting_client.get_task_completion_trends.assert_awaited_once_with(
            user_id=self.user.id, request_id="analytics-task-trends-1"
        )
        self.meeting_client.get_speaker_participation.assert_awaited_once_with(
            meetings_limit=9,
            user_id=self.user.id,
            request_id="analytics-speakers-1",
        )
        self.assertEqual(
            self.client.get("/api/v1/analytics/speaker-participation?meetings_limit=101").status_code,
            422,
        )
        self.assertEqual(self.meeting_client.get_speaker_participation.await_count, 1)

    def test_meeting_client_signs_audience_and_forwards_request_id(self):
        from cryptography.hazmat.primitives import serialization
        from shared.security.internal_principal import verify_internal_principal
        from app.config.settings import GatewaySettings
        from app.services.meeting_client import MeetingServiceClient
        from shared.jobs.lifecycle import JobStatus
        from shared.schemas.followup import FollowupStatus
        from shared.schemas.meeting import MeetingStatus
        from httpx import Response

        settings = GatewaySettings(_env_file=None)
        private_key = serialization.load_pem_private_key(
            settings.internal_principal_private_key.get_secret_value().encode(),
            password=None,
        )
        public_pem = private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
        client_module = importlib.import_module("app.services.meeting_client")
        downstream = MagicMock()
        downstream.request = AsyncMock(return_value=Response(200, json={
            "total_meetings": 0, "meetings_per_week": [], "open_tasks": 0,
            "completed_tasks": 0, "overdue_tasks": 0, "decisions": 0,
            "followups": 0,
            "followup_status_counts": {status.value: 0 for status in FollowupStatus},
            "meeting_status_counts": {status.value: 0 for status in MeetingStatus},
            "processing_job_status_counts": {status.value: 0 for status in JobStatus},
        }))
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=downstream)
        context.__aexit__ = AsyncMock(return_value=False)
        client = MeetingServiceClient(settings)

        async def invoke():
            with patch.object(client_module.httpx, "AsyncClient", return_value=context):
                return await client.get_analytics_overview(
                    weeks=3, user_id=self.user.id, request_id="analytics-internal-1"
                )

        from shared.schemas.analytics import AnalyticsOverviewResponse
        result = asyncio.run(invoke())
        self.assertIsInstance(result, AnalyticsOverviewResponse)
        args, kwargs = downstream.request.await_args
        self.assertEqual(args, ("GET", "/analytics/overview?weeks=3"))
        self.assertEqual(kwargs["headers"]["X-Request-ID"], "analytics-internal-1")
        principal = kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        identity = verify_internal_principal(
            principal,
            public_key=public_pem,
            algorithm=settings.internal_principal_algorithm,
            issuer=settings.internal_principal_issuer,
            audience="meeting-service",
        )
        self.assertEqual(identity, self.user.id)

    def test_meeting_client_trends_forwards_bounded_parameters_and_principal(self):
        from cryptography.hazmat.primitives import serialization
        from httpx import Response
        from shared.jobs.lifecycle import JobStatus
        from shared.schemas.followup import FollowupStatus
        from shared.schemas.meeting import MeetingStatus
        from shared.security.internal_principal import verify_internal_principal
        from app.config.settings import GatewaySettings
        from app.services.meeting_client import MeetingServiceClient

        settings = GatewaySettings(_env_file=None)
        private_key = serialization.load_pem_private_key(
            settings.internal_principal_private_key.get_secret_value().encode(),
            password=None,
        )
        public_pem = private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
        client_module = importlib.import_module("app.services.meeting_client")
        downstream = MagicMock()
        downstream.request = AsyncMock(return_value=Response(200, json={
            "decision_trends": [], "meeting_frequency": [], "topic_trends": [],
        }))
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=downstream)
        context.__aexit__ = AsyncMock(return_value=False)
        client = MeetingServiceClient(settings)

        async def invoke():
            with patch.object(client_module.httpx, "AsyncClient", return_value=context):
                return await client.get_analytics_trends(
                    weeks=5,
                    topics_per_week=7,
                    user_id=self.user.id,
                    request_id="analytics-trends-internal-1",
                )

        from shared.schemas.analytics import AnalyticsTrendsResponse
        result = asyncio.run(invoke())
        self.assertIsInstance(result, AnalyticsTrendsResponse)
        args, kwargs = downstream.request.await_args
        self.assertEqual(
            args,
            ("GET", "/analytics/trends?weeks=5&topics_per_week=7"),
        )
        self.assertEqual(kwargs["headers"]["X-Request-ID"], "analytics-trends-internal-1")
        principal = kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        identity = verify_internal_principal(
            principal,
            public_key=public_pem,
            algorithm=settings.internal_principal_algorithm,
            issuer=settings.internal_principal_issuer,
            audience="meeting-service",
        )
        self.assertEqual(identity, self.user.id)

    def test_meeting_client_sanitizes_trends_downstream_failures(self):
        from app.config.settings import GatewaySettings
        from app.services.meeting_client import MeetingServiceClient
        from httpx import Response
        from shared.exceptions.common import ServiceUnavailableError

        settings = GatewaySettings(_env_file=None)
        client_module = importlib.import_module("app.services.meeting_client")
        downstream = MagicMock()
        downstream.request = AsyncMock(return_value=Response(500, json={
            "error": {"message": "database_password=do-not-return"}
        }))
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=downstream)
        context.__aexit__ = AsyncMock(return_value=False)
        client = MeetingServiceClient(settings)

        async def invoke():
            with patch.object(client_module.httpx, "AsyncClient", return_value=context):
                return await client.get_analytics_trends(
                    weeks=2,
                    topics_per_week=5,
                    user_id=self.user.id,
                    request_id="analytics-trends-failure-1",
                )

        with self.assertRaises(ServiceUnavailableError) as raised:
            asyncio.run(invoke())
        self.assertEqual(str(raised.exception), "Meeting service is unavailable.")

    def test_meeting_client_signs_principal_for_recurring_blockers(self):
        from cryptography.hazmat.primitives import serialization
        from httpx import Response
        from shared.security.internal_principal import verify_internal_principal
        from app.config.settings import GatewaySettings
        from app.services.meeting_client import MeetingServiceClient

        settings = GatewaySettings(_env_file=None)
        private_key = serialization.load_pem_private_key(
            settings.internal_principal_private_key.get_secret_value().encode(),
            password=None,
        )
        public_pem = private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
        client_module = importlib.import_module("app.services.meeting_client")
        downstream = MagicMock()
        downstream.request = AsyncMock(return_value=Response(200, json={"recurring_blockers": []}))
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=downstream)
        context.__aexit__ = AsyncMock(return_value=False)
        client = MeetingServiceClient(settings)

        async def invoke():
            with patch.object(client_module.httpx, "AsyncClient", return_value=context):
                return await client.get_recurring_blockers(
                    user_id=self.user.id, request_id="analytics-blockers-internal-1"
                )

        from shared.schemas.analytics import RecurringBlockersResponse
        self.assertIsInstance(asyncio.run(invoke()), RecurringBlockersResponse)
        args, kwargs = downstream.request.await_args
        self.assertEqual(args, ("GET", "/analytics/recurring-blockers"))
        self.assertEqual(kwargs["headers"]["X-Request-ID"], "analytics-blockers-internal-1")
        principal = kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        self.assertEqual(
            verify_internal_principal(
                principal,
                public_key=public_pem,
                algorithm=settings.internal_principal_algorithm,
                issuer=settings.internal_principal_issuer,
                audience="meeting-service",
            ),
            self.user.id,
        )

    def test_meeting_client_signs_principal_for_task_and_speaker_analytics(self):
        from cryptography.hazmat.primitives import serialization
        from httpx import Response
        from shared.security.internal_principal import verify_internal_principal
        from app.config.settings import GatewaySettings
        from app.services.meeting_client import MeetingServiceClient

        settings = GatewaySettings(_env_file=None)
        private_key = serialization.load_pem_private_key(
            settings.internal_principal_private_key.get_secret_value().encode(), password=None
        )
        public_pem = private_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode()
        client_module = importlib.import_module("app.services.meeting_client")
        downstream = MagicMock()
        downstream.request = AsyncMock(side_effect=[
            Response(200, json={"available": False, "reason": "No task history."}),
            Response(200, json={"total_transcripts": 0, "meetings": [], "truncated": False}),
        ])
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=downstream)
        context.__aexit__ = AsyncMock(return_value=False)
        client = MeetingServiceClient(settings)

        async def invoke():
            with patch.object(client_module.httpx, "AsyncClient", return_value=context):
                task = await client.get_task_completion_trends(
                    user_id=self.user.id, request_id="analytics-task-internal-1"
                )
                speakers = await client.get_speaker_participation(
                    meetings_limit=9,
                    user_id=self.user.id,
                    request_id="analytics-speakers-internal-1",
                )
                return task, speakers

        from shared.schemas.analytics import SpeakerParticipationResponse, TaskCompletionTrendsResponse
        task, speakers = asyncio.run(invoke())
        self.assertIsInstance(task, TaskCompletionTrendsResponse)
        self.assertIsInstance(speakers, SpeakerParticipationResponse)
        calls = downstream.request.await_args_list
        self.assertEqual(calls[0].args, ("GET", "/analytics/task-completion-trends"))
        self.assertEqual(calls[1].args, ("GET", "/analytics/speaker-participation?meetings_limit=9"))
        for call, request_id in zip(
            calls,
            ("analytics-task-internal-1", "analytics-speakers-internal-1"),
        ):
            headers = call.kwargs["headers"]
            self.assertEqual(headers["X-Request-ID"], request_id)
            principal = headers["Authorization"].removeprefix("Bearer ")
            self.assertEqual(
                verify_internal_principal(
                    principal,
                    public_key=public_pem,
                    algorithm=settings.internal_principal_algorithm,
                    issuer=settings.internal_principal_issuer,
                    audience="meeting-service",
                ),
                self.user.id,
            )

    def test_meeting_client_sanitizes_task_and_speaker_analytics_failures(self):
        from app.config.settings import GatewaySettings
        from app.services.meeting_client import MeetingServiceClient
        from httpx import Response
        from shared.exceptions.common import ServiceUnavailableError

        settings = GatewaySettings(_env_file=None)
        client_module = importlib.import_module("app.services.meeting_client")
        downstream = MagicMock()
        downstream.request = AsyncMock(side_effect=[
            Response(500, json={"error": {"message": "password=private"}}),
            Response(502, json={"error": {"message": "token=private"}}),
        ])
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=downstream)
        context.__aexit__ = AsyncMock(return_value=False)
        client = MeetingServiceClient(settings)

        async def invoke():
            with patch.object(client_module.httpx, "AsyncClient", return_value=context):
                errors = []
                for operation in (
                    lambda: client.get_task_completion_trends(
                        user_id=self.user.id, request_id="task-fail"
                    ),
                    lambda: client.get_speaker_participation(
                        meetings_limit=5, user_id=self.user.id, request_id="speaker-fail"
                    ),
                ):
                    try:
                        await operation()
                    except ServiceUnavailableError as exc:
                        errors.append(str(exc))
                return errors

        self.assertEqual(
            asyncio.run(invoke()),
            ["Meeting service is unavailable.", "Meeting service is unavailable."],
        )

    def test_meeting_client_sanitizes_recurring_blocker_downstream_failure(self):
        from app.config.settings import GatewaySettings
        from app.services.meeting_client import MeetingServiceClient
        from httpx import Response
        from shared.exceptions.common import ServiceUnavailableError

        settings = GatewaySettings(_env_file=None)
        client_module = importlib.import_module("app.services.meeting_client")
        downstream = MagicMock()
        downstream.request = AsyncMock(return_value=Response(500, json={
            "error": {"message": "secret=must-not-leak"}
        }))
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=downstream)
        context.__aexit__ = AsyncMock(return_value=False)
        client = MeetingServiceClient(settings)

        async def invoke():
            with patch.object(client_module.httpx, "AsyncClient", return_value=context):
                return await client.get_recurring_blockers(
                    user_id=self.user.id, request_id="analytics-blockers-failure-1"
                )

        with self.assertRaises(ServiceUnavailableError) as raised:
            asyncio.run(invoke())
        self.assertEqual(str(raised.exception), "Meeting service is unavailable.")


if __name__ == "__main__":
    unittest.main()
