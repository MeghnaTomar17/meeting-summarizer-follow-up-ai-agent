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
        self.service.list_meetings = AsyncMock()
        self.service.update_meeting = AsyncMock()
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

    def test_list_meetings_returns_paginated_dtos_and_forwards_pagination(self) -> None:
        from shared.schemas.pagination import build_paginated_response

        organization_id = uuid.uuid4()
        meetings = [self._meeting_public(), self._meeting_public()]
        self.service.list_meetings.return_value = build_paginated_response(
            meetings,
            page=2,
            page_size=2,
            total=5,
        )

        response = self.client.get(
            "/meetings",
            params={
                "organization_id": str(organization_id),
                "page": 2,
                "page_size": 2,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()["items"]], [
            meeting.id for meeting in meetings
        ])
        self.assertEqual(
            response.json()["pagination"],
            {"page": 2, "page_size": 2, "total": 5, "total_pages": 3},
        )
        self.service.list_meetings.assert_awaited_once_with(
            str(organization_id),
            page=2,
            limit=2,
            offset=2,
        )
        self.service.create_meeting.assert_not_called()
        self.service.get_meeting.assert_not_called()

    def test_list_meetings_returns_empty_page(self) -> None:
        from shared.schemas.pagination import build_paginated_response

        self.service.list_meetings.return_value = build_paginated_response(
            [],
            page=1,
            page_size=20,
            total=0,
        )

        response = self.client.get(
            "/meetings",
            params={"organization_id": str(uuid.uuid4())},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"], [])
        self.assertEqual(
            response.json()["pagination"],
            {"page": 1, "page_size": 20, "total": 0, "total_pages": 0},
        )

    def test_list_meetings_invalid_organization_id_uses_standard_validation_response(
        self,
    ) -> None:
        from shared.exceptions.common import ValidationError

        self.service.list_meetings.side_effect = ValidationError(
            "Invalid organization ID."
        )

        response = self.client.get(
            "/meetings",
            params={"organization_id": "not-a-uuid"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")
        self.assertEqual(
            response.json()["error"]["message"], "Invalid organization ID."
        )

    def test_list_meetings_rejects_invalid_pagination_before_calling_service(self) -> None:
        response = self.client.get(
            "/meetings",
            params={"organization_id": str(uuid.uuid4()), "page": 0},
        )

        self.assertEqual(response.status_code, 422)
        self.service.list_meetings.assert_not_called()

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

    def test_update_meeting_returns_dto_from_service(self) -> None:
        meeting_id = uuid.uuid4()
        updated = self._meeting_public(meeting_id)
        updated.title = "Updated planning meeting"
        self.service.update_meeting.return_value = updated
        payload = {"title": "Updated planning meeting"}

        response = self.client.patch(f"/meetings/{meeting_id}", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(meeting_id))
        self.assertEqual(response.json()["title"], "Updated planning meeting")
        submitted = self.service.update_meeting.await_args.args
        self.assertEqual(submitted[0], str(meeting_id))
        self.assertEqual(submitted[1].model_dump(exclude_unset=True), payload)
        self.service.create_meeting.assert_not_called()
        self.service.get_meeting.assert_not_called()
        self.service.list_meetings.assert_not_called()

    def test_update_missing_meeting_uses_standard_not_found_response(self) -> None:
        from shared.exceptions.common import NotFoundError

        self.service.update_meeting.side_effect = NotFoundError("Meeting not found.")

        response = self.client.patch(
            f"/meetings/{uuid.uuid4()}",
            json={"title": "Updated planning meeting"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "NOT_FOUND")
        self.assertEqual(response.json()["error"]["message"], "Meeting not found.")

    def test_update_invalid_meeting_id_uses_standard_validation_response(self) -> None:
        from shared.exceptions.common import ValidationError

        self.service.update_meeting.side_effect = ValidationError("Invalid meeting ID.")

        response = self.client.patch(
            "/meetings/not-a-uuid",
            json={"title": "Updated planning meeting"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")
        self.assertEqual(response.json()["error"]["message"], "Invalid meeting ID.")

    def test_update_rejects_null_title_before_calling_service(self) -> None:
        response = self.client.patch(
            f"/meetings/{uuid.uuid4()}",
            json={"title": None},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")
        self.service.update_meeting.assert_not_called()

    def test_update_rejects_null_participants_before_calling_service(self) -> None:
        response = self.client.patch(
            f"/meetings/{uuid.uuid4()}",
            json={"participants": None},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")
        self.service.update_meeting.assert_not_called()

    def test_update_unexpected_error_uses_safe_standard_response(self) -> None:
        self.service.update_meeting.side_effect = RuntimeError("database failed")

        response = self.client.patch(
            f"/meetings/{uuid.uuid4()}",
            json={"title": "Updated planning meeting"},
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "INTERNAL_SERVER_ERROR")


if __name__ == "__main__":
    unittest.main()
