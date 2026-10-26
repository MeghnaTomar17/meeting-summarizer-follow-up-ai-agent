"""Public API v1 contract tests for meeting-owned result resources."""

from __future__ import annotations

import importlib
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
GATEWAY_ROOT = BACKEND_ROOT / "gateway-service"


def _load_app() -> tuple[FastAPI, object, object]:
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    sys.path.insert(0, str(GATEWAY_ROOT))
    main = importlib.import_module("app.main")
    routes = importlib.import_module("app.routes.meeting_results")
    auth = importlib.import_module("app.auth.dependencies")
    return main.app, routes.get_meeting_client, auth.get_current_user


class GatewayMeetingResultsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.app, client_dependency, auth_dependency = _load_app()
        self.user = SimpleNamespace(id=uuid.uuid4())
        self.client_stub = MagicMock()
        for method in (
            "create_summary", "list_summaries", "get_summary", "create_task", "list_tasks",
            "get_task", "update_task", "create_decision", "list_decisions", "get_decision",
            "create_followup", "list_followups", "get_followup", "update_followup",
        ):
            setattr(self.client_stub, method, AsyncMock())
        self.client_stub.list_meeting_insights = AsyncMock()
        self.client_stub.get_meeting_processing_status = AsyncMock()
        self.app.dependency_overrides[client_dependency] = lambda: self.client_stub
        self.app.dependency_overrides[auth_dependency] = lambda: self.user
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def tearDown(self) -> None:
        self.client.close()
        self.app.dependency_overrides.clear()

    def test_gateway_exposes_expected_v1_domain_routes(self) -> None:
        paths = self.app.openapi()["paths"]
        for suffix, methods in {
            "insights": {"get"},
            "processing-status": {"get"},
            "summaries": {"get", "post"},
            "summaries/latest": {"get"},
            "summaries/{summary_id}": {"get"},
            "tasks": {"get", "post"},
            "tasks/{task_id}": {"get", "patch"},
            "decisions": {"get", "post"},
            "decisions/{decision_id}": {"get"},
            "followups": {"get", "post"},
            "followups/{followup_id}": {"get", "patch"},
        }.items():
            path = f"/api/v1/meetings/{{meeting_id}}/{suffix}"
            self.assertTrue(methods.issubset(paths[path].keys()), path)

    def test_insights_and_processing_status_forward_authenticated_identity_and_request_id(self) -> None:
        from shared.schemas.meeting_insight import MeetingInsightInDB
        from shared.schemas.pagination import build_paginated_response
        from shared.schemas.processing_status import MeetingProcessingStatus

        meeting_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        self.client_stub.list_meeting_insights.return_value = build_paginated_response(
            [MeetingInsightInDB(id=str(uuid.uuid4()), meeting_id=meeting_id, category="risk", title="Risk", description="Schedule risk", created_at=now)],
            page=1, page_size=20, total=1,
        )
        self.client_stub.get_meeting_processing_status.return_value = MeetingProcessingStatus(meeting_id=uuid.UUID(meeting_id), status="running", updated_at=now)
        headers = {"X-Request-ID": "details-read-1"}
        insights = self.client.get(f"/api/v1/meetings/{meeting_id}/insights", headers=headers)
        status_response = self.client.get(f"/api/v1/meetings/{meeting_id}/processing-status", headers=headers)
        self.assertEqual(insights.status_code, 200, insights.text)
        self.assertEqual(insights.json()["items"][0]["title"], "Risk")
        self.assertEqual(status_response.status_code, 200, status_response.text)
        self.assertEqual(status_response.json()["status"], "running")
        self.client_stub.list_meeting_insights.assert_awaited_once_with(
            meeting_id, page=1, page_size=20, user_id=self.user.id, request_id="details-read-1"
        )
        self.client_stub.get_meeting_processing_status.assert_awaited_once_with(
            meeting_id, user_id=self.user.id, request_id="details-read-1"
        )

    def test_public_create_rejects_owner_fields_and_forwards_authenticated_identity(self) -> None:
        from shared.schemas.summary import SummaryInDB

        now = datetime.now(timezone.utc)
        meeting_id = str(uuid.uuid4())
        dto = SummaryInDB(id=str(uuid.uuid4()), meeting_id=meeting_id, content="Summary", key_topics=[], version=1, created_at=now)
        self.client_stub.create_summary.return_value = dto
        path = f"/api/v1/meetings/{meeting_id}/summaries"
        rejected = self.client.post(path, json={"content": "Summary", "created_by": str(uuid.uuid4())})
        self.assertEqual(rejected.status_code, 422)
        self.client_stub.create_summary.assert_not_awaited()
        response = self.client.post(path, json={"content": "Summary"}, headers={"X-Request-ID": "phase5-results"})
        self.assertEqual(response.status_code, 201)
        payload = self.client_stub.create_summary.await_args.args[1]
        self.assertEqual(payload.meeting_id, meeting_id)
        self.assertEqual(self.client_stub.create_summary.await_args.kwargs["user_id"], self.user.id)
        self.assertEqual(self.client_stub.create_summary.await_args.kwargs["request_id"], "phase5-results")


if __name__ == "__main__":
    unittest.main()
