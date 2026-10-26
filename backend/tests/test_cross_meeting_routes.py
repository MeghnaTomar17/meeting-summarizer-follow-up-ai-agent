"""Meeting Service internal route authorization and request-contract tests."""

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
    route = importlib.import_module("app.routes.cross_meeting")
    auth = importlib.import_module("app.auth.dependencies")
    return main.app, route, auth


class CrossMeetingRouteTests(unittest.TestCase):
    def setUp(self):
        self.app, self.route, self.auth = _load_app()
        self.owner_id = uuid.uuid4()
        self.service = MagicMock()
        self.service.query = AsyncMock()
        self.app.dependency_overrides[self.route.get_cross_meeting_service] = lambda: self.service
        self.app.dependency_overrides[self.auth.get_authenticated_user_id] = lambda: self.owner_id
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def tearDown(self):
        self.client.close()
        self.app.dependency_overrides.clear()

    def test_internal_route_derives_scope_from_principal_and_rejects_owner_body(self):
        from shared.schemas.cross_meeting import CrossMeetingDataQuery

        self.service.query.return_value = CrossMeetingDataQuery  # replaced below with typed response
        from shared.schemas.cross_meeting import CrossMeetingStructuredData
        from shared.schemas.pagination import build_paginated_response

        empty = build_paginated_response([], page=1, page_size=20, total=0)
        self.service.query.return_value = CrossMeetingStructuredData(
            meetings=empty, tasks=empty, decisions=empty, insights=empty
        )
        response = self.client.post("/intelligence/structured-data", json={"task_filter": "unresolved"})
        self.assertEqual(response.status_code, 200, response.text)
        self.service.query.assert_awaited_once()
        self.assertEqual(self.service.query.await_args.kwargs["owner_id"], self.owner_id)
        self.assertEqual(self.service.query.await_args.args[0].task_filter.value, "unresolved")

        rejected = self.client.post(
            "/intelligence/structured-data",
            json={"owner_id": str(uuid.uuid4())},
        )
        self.assertEqual(rejected.status_code, 422)
        self.assertEqual(self.service.query.await_count, 1)

    def test_missing_internal_principal_is_rejected_before_service(self):
        self.app.dependency_overrides.pop(self.auth.get_authenticated_user_id)
        response = self.client.post("/intelligence/structured-data", json={})
        self.assertEqual(response.status_code, 401)
        invalid = self.client.post(
            "/intelligence/structured-data",
            json={},
            headers={"Authorization": "Bearer invalid-principal"},
        )
        self.assertEqual(invalid.status_code, 401)
        self.service.query.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
