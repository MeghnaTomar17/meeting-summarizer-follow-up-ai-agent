"""Gateway authentication and typed proxy tests for structured cross-meeting data."""

from __future__ import annotations

import importlib
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
GATEWAY_ROOT = BACKEND_ROOT / "gateway-service"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _load_app():
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    while str(GATEWAY_ROOT) in sys.path:
        sys.path.remove(str(GATEWAY_ROOT))
    sys.path.insert(0, str(GATEWAY_ROOT))
    main = importlib.import_module("app.main")
    route = importlib.import_module("app.routes.cross_meeting")
    meeting_routes = importlib.import_module("app.routes.meetings")
    auth = importlib.import_module("app.auth.dependencies")
    return main.app, route, meeting_routes, auth


class GatewayCrossMeetingTests(unittest.TestCase):
    def setUp(self):
        self.app, self.route, self.meeting_routes, self.auth = _load_app()
        from shared.database.models.user import User

        now = datetime.now(timezone.utc)
        self.user = User(id=uuid.uuid4(), email="owner@example.com", password_hash="hash", created_at=now, updated_at=now)
        self.client_service = MagicMock()
        from shared.schemas.cross_meeting import CrossMeetingStructuredData
        from shared.schemas.pagination import build_paginated_response
        empty = build_paginated_response([], page=1, page_size=20, total=0)
        self.response_model = CrossMeetingStructuredData(
            meetings=empty, tasks=empty, decisions=empty, insights=empty
        )
        self.client_service.query_cross_meeting_data = AsyncMock(return_value=self.response_model)
        from shared.schemas.semantic_search import SemanticSearchResponse
        from shared.schemas.cross_meeting import CrossMeetingEvidenceBundle
        self.evidence_bundle = CrossMeetingEvidenceBundle(
            structured=self.response_model,
            semantic=SemanticSearchResponse(results=[]),
        )
        self.evidence_service = MagicMock()
        self.evidence_service.retrieve = AsyncMock(return_value=self.evidence_bundle)
        self.evidence_service.answer = AsyncMock(return_value={
            "answer": "The evidence supports this.",
            "insufficient_evidence": False,
            "citations": [],
        })
        self.app.dependency_overrides[self.auth.get_current_user] = lambda: self.user
        self.app.dependency_overrides[self.meeting_routes.get_meeting_client] = lambda: self.client_service
        self.app.dependency_overrides[
            self.route.get_cross_meeting_evidence_service
        ] = lambda: self.evidence_service
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def tearDown(self):
        self.client.close()
        self.app.dependency_overrides.clear()

    def test_gateway_uses_authenticated_user_and_rejects_client_owner_override(self):
        response = self.client.post(
            "/api/v1/intelligence/structured-data",
            json={"task_filter": "overdue", "page_size": 10},
            headers={"X-Request-ID": "cross-meeting-1"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.client_service.query_cross_meeting_data.assert_awaited_once()
        call = self.client_service.query_cross_meeting_data.await_args
        kwargs = call.kwargs
        self.assertEqual(kwargs["user_id"], self.user.id)
        self.assertEqual(kwargs["request_id"], "cross-meeting-1")
        self.assertEqual(call.args[0].task_filter.value, "overdue")

        rejected = self.client.post(
            "/api/v1/intelligence/structured-data",
            json={"owner_id": str(uuid.uuid4())},
        )
        self.assertEqual(rejected.status_code, 422)
        self.assertEqual(self.client_service.query_cross_meeting_data.await_count, 1)

    def test_gateway_does_not_call_meeting_service_without_external_authentication(self):
        from shared.database.session import get_db_session

        self.app.dependency_overrides.pop(self.auth.get_current_user)
        self.app.dependency_overrides[get_db_session] = lambda: MagicMock()
        response = self.client.post("/api/v1/intelligence/structured-data", json={})
        self.assertEqual(response.status_code, 401)
        self.client_service.query_cross_meeting_data.assert_not_awaited()
        evidence = self.client.post(
            "/api/v1/intelligence/evidence",
            json={"semantic": {"query": "q"}, "structured": {}},
        )
        self.assertEqual(evidence.status_code, 401)
        self.evidence_service.retrieve.assert_not_awaited()

    def test_evidence_route_uses_authenticated_owner_and_propagates_request_id(self):
        response = self.client.post(
            "/api/v1/intelligence/evidence",
            json={
                "semantic": {"query": "What blocks Atlas?", "top_k": 4},
                "structured": {"task_filter": "unresolved", "page_size": 5},
            },
            headers={"X-Request-ID": "evidence-gateway-1"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["semantic"]["results"], [])
        self.evidence_service.retrieve.assert_awaited_once()
        call = self.evidence_service.retrieve.await_args
        self.assertEqual(call.kwargs["user_id"], self.user.id)
        self.assertEqual(call.kwargs["request_id"], "evidence-gateway-1")
        self.assertEqual(call.args[0].semantic.top_k, 4)
        self.assertEqual(call.args[0].structured.page_size, 5)

        for payload in (
            {
                "owner_id": str(uuid.uuid4()),
                "semantic": {"query": "q"},
                "structured": {},
            },
            {
                "semantic": {"query": "q", "owner_id": str(uuid.uuid4())},
                "structured": {},
            },
        ):
            rejected = self.client.post("/api/v1/intelligence/evidence", json=payload)
            self.assertEqual(rejected.status_code, 422)
        self.assertEqual(self.evidence_service.retrieve.await_count, 1)

    def test_question_route_keeps_owner_and_request_id_from_trusted_context(self):
        response = self.client.post(
            "/api/v1/intelligence/questions",
            json={"question": "What decisions were made?", "top_k": 4,
                  "structured": {"page_size": 7}},
            headers={"X-Request-ID": "question-gateway-1"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        call = self.evidence_service.answer.await_args
        self.assertEqual(call.kwargs["user_id"], self.user.id)
        self.assertEqual(call.kwargs["request_id"], "question-gateway-1")
        self.assertEqual(call.args[0].question, "What decisions were made?")
        self.assertEqual(call.args[0].structured.page_size, 7)
        rejected = self.client.post(
            "/api/v1/intelligence/questions",
            json={"question": "Question?", "owner_id": str(uuid.uuid4())},
        )
        self.assertEqual(rejected.status_code, 422)
        self.assertEqual(self.evidence_service.answer.await_count, 1)


if __name__ == "__main__":
    unittest.main()
