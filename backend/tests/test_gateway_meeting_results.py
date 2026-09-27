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
        self.app.dependency_overrides[client_dependency] = lambda: self.client_stub
        self.app.dependency_overrides[auth_dependency] = lambda: self.user
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def tearDown(self) -> None:
        self.client.close()
        self.app.dependency_overrides.clear()

    def test_gateway_exposes_expected_v1_domain_routes(self) -> None:
        paths = self.app.openapi()["paths"]
        for suffix, methods in {
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
