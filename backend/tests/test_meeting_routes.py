"""Route tests for the internal meeting-service Meeting API slice."""

from __future__ import annotations

import importlib
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MEETING_ROOT = BACKEND_ROOT / "meeting-service"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _load_meeting_app() -> tuple[FastAPI, object]:
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]
    while str(MEETING_ROOT) in sys.path:
        sys.path.remove(str(MEETING_ROOT))
    sys.path.insert(0, str(MEETING_ROOT))

    main_module = importlib.import_module("app.main")
    routes_module = importlib.import_module("app.routes.meetings")
    return main_module.app, routes_module.get_meeting_service


class MeetingRouteTestCase(unittest.TestCase):
    def setUp(self) -> None:
        from shared.config.base import AppEnv
        from shared.utils.logger import configure_logging

        configure_logging(
            service_name="meeting-service",
            log_level="INFO",
            app_env=AppEnv.DEVELOPMENT,
        )
        self.app, self.service_dependency = _load_meeting_app()
        self.service = MagicMock()
        self.service.create_meeting = AsyncMock()
        self.service.get_meeting = AsyncMock()
        self.app.dependency_overrides[self.service_dependency] = lambda: self.service
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def tearDown(self) -> None:
        self.client.close()
        self.app.dependency_overrides.clear()

    @staticmethod
    def _meeting_payload() -> dict[str, object]:
        return {
            "organization_id": str(uuid.uuid4()),
            "created_by": str(uuid.uuid4()),
            "title": "Planning meeting",
            "description": "Quarterly planning",
            "participants": ["alice@example.com"],
        }

    @staticmethod
    def _meeting_public(meeting_id: uuid.UUID | None = None):
        from shared.schemas.meeting import MeetingPublic, MeetingStatus

        now = datetime.now(timezone.utc)
        return MeetingPublic(
            id=str(meeting_id or uuid.uuid4()),
            title="Planning meeting",
            description="Quarterly planning",
            participants=["alice@example.com"],
            status=MeetingStatus.PENDING,
            created_at=now,
            updated_at=now,
        )

    def test_meetings_router_is_mounted(self) -> None:
        paths = [route.path for route in self.app.routes]
        self.assertIn("/meetings", paths)
        self.assertIn("/meetings/{meeting_id}", paths)

    def test_create_meeting_returns_created_dto_from_service(self) -> None:
        created = self._meeting_public()
        self.service.create_meeting.return_value = created
        payload = self._meeting_payload()

        response = self.client.post("/meetings", json=payload)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["id"], created.id)
        self.assertEqual(response.json()["status"], "pending")
        submitted = self.service.create_meeting.await_args.args[0]
        self.assertEqual(submitted.model_dump(exclude_none=True), payload)
        self.service.get_meeting.assert_not_called()

    def test_get_meeting_returns_dto_from_service(self) -> None:
        meeting_id = uuid.uuid4()
        meeting = self._meeting_public(meeting_id)
        self.service.get_meeting.return_value = meeting

        response = self.client.get(f"/meetings/{meeting_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(meeting_id))
        self.service.get_meeting.assert_awaited_once_with(str(meeting_id))
        self.service.create_meeting.assert_not_called()

    def test_missing_meeting_uses_standard_not_found_response(self) -> None:
        from shared.exceptions.common import NotFoundError

        self.service.get_meeting.side_effect = NotFoundError("Meeting not found.")

        response = self.client.get(f"/meetings/{uuid.uuid4()}")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "NOT_FOUND")
        self.assertEqual(response.json()["error"]["message"], "Meeting not found.")
        self.assertIn("X-Request-ID", response.headers)

    def test_invalid_meeting_id_uses_standard_validation_response(self) -> None:
        from shared.exceptions.common import ValidationError

        self.service.get_meeting.side_effect = ValidationError("Invalid meeting ID.")

        response = self.client.get("/meetings/not-a-uuid")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")
        self.assertEqual(response.json()["error"]["message"], "Invalid meeting ID.")


if __name__ == "__main__":
    unittest.main()
