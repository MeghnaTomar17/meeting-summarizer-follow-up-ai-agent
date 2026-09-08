"""Route tests for internal meeting-service transcript APIs."""

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


class TranscriptRouteTestCase(unittest.TestCase):
    def setUp(self) -> None:
        from shared.config.base import AppEnv
        from shared.utils.logger import configure_logging

        configure_logging(
            service_name="meeting-service",
            log_level="INFO",
            app_env=AppEnv.DEVELOPMENT,
        )
        self.app, self.service_dependency = _load_meeting_app()
        from app.auth.dependencies import get_authenticated_user_id

        self.authenticated_user_id = uuid.uuid4()
        self.service = MagicMock()
        self.service.create_transcript = AsyncMock()
        self.service.get_transcript = AsyncMock()
        self.service.replace_transcript = AsyncMock()
        self.app.dependency_overrides[self.service_dependency] = lambda: self.service
        self.app.dependency_overrides[get_authenticated_user_id] = lambda: self.authenticated_user_id
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def tearDown(self) -> None:
        self.client.close()
        self.app.dependency_overrides.clear()

    @staticmethod
    def _payload() -> dict[str, object]:
        return {
            "segments": [{"index": 0, "text": "Plan the release."}],
            "language": "en",
        }

    @staticmethod
    def _transcript(meeting_id: uuid.UUID):
        from shared.schemas.transcript import TranscriptInDB

        now = datetime.now(timezone.utc)
        return TranscriptInDB(
            id=str(uuid.uuid4()),
            meeting_id=str(meeting_id),
            segments=[{"index": 0, "text": "Plan the release."}],
            language="en",
            created_at=now,
            updated_at=now,
        )

    def test_transcript_router_is_mounted(self) -> None:
        paths = [route.path for route in self.app.routes]
        self.assertIn("/meetings/{meeting_id}/transcript", paths)

    def test_create_transcript_adapts_authoritative_path_id_and_returns_dto(self) -> None:
        meeting_id = uuid.uuid4()
        transcript = self._transcript(meeting_id)
        self.service.create_transcript.return_value = transcript
        payload = self._payload()

        response = self.client.post(f"/meetings/{meeting_id}/transcript", json=payload)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["id"], transcript.id)
        self.assertEqual(response.json()["meeting_id"], str(meeting_id))
        submitted = self.service.create_transcript.await_args.args[0]
        self.assertEqual(submitted.meeting_id, str(meeting_id))
        self.assertEqual(submitted.segments[0].text, "Plan the release.")
        self.assertEqual(submitted.language, "en")

    def test_create_transcript_missing_parent_uses_standard_not_found_response(self) -> None:
        from shared.exceptions.common import NotFoundError

        self.service.create_transcript.side_effect = NotFoundError("Meeting not found.")

        response = self.client.post(
            f"/meetings/{uuid.uuid4()}/transcript",
            json=self._payload(),
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "NOT_FOUND")

    def test_create_transcript_duplicate_uses_standard_conflict_response(self) -> None:
        from shared.exceptions.common import ConflictError

        self.service.create_transcript.side_effect = ConflictError(
            "Transcript already exists."
        )

        response = self.client.post(
            f"/meetings/{uuid.uuid4()}/transcript",
            json=self._payload(),
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "CONFLICT")

    def test_get_transcript_forwards_path_id_and_returns_dto(self) -> None:
        meeting_id = uuid.uuid4()
        transcript = self._transcript(meeting_id)
        self.service.get_transcript.return_value = transcript

        response = self.client.get(f"/meetings/{meeting_id}/transcript")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["meeting_id"], str(meeting_id))
        self.service.get_transcript.assert_awaited_once_with(
            str(meeting_id),
            self.authenticated_user_id,
        )

    def test_get_missing_transcript_uses_standard_not_found_response(self) -> None:
        from shared.exceptions.common import NotFoundError

        self.service.get_transcript.side_effect = NotFoundError("Transcript not found.")

        response = self.client.get(f"/meetings/{uuid.uuid4()}/transcript")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "NOT_FOUND")

    def test_replace_transcript_forwards_path_content_and_returns_dto(self) -> None:
        meeting_id = uuid.uuid4()
        transcript = self._transcript(meeting_id)
        self.service.replace_transcript.return_value = transcript
        payload = self._payload()

        response = self.client.put(f"/meetings/{meeting_id}/transcript", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], transcript.id)
        self.service.replace_transcript.assert_awaited_once()
        self.assertEqual(
            self.service.replace_transcript.await_args.args,
            (str(meeting_id),),
        )
        self.assertEqual(
            self.service.replace_transcript.await_args.kwargs["language"],
            "en",
        )
        segments = self.service.replace_transcript.await_args.kwargs["segments"]
        self.assertEqual(segments[0].text, "Plan the release.")

    def test_replace_missing_transcript_returns_not_found_without_creating(self) -> None:
        from shared.exceptions.common import NotFoundError

        self.service.replace_transcript.side_effect = NotFoundError(
            "Transcript not found."
        )

        response = self.client.put(
            f"/meetings/{uuid.uuid4()}/transcript",
            json=self._payload(),
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "NOT_FOUND")
        self.service.create_transcript.assert_not_called()

    def test_invalid_path_id_uses_standard_validation_response(self) -> None:
        from shared.exceptions.common import ValidationError

        self.service.get_transcript.side_effect = ValidationError("Invalid meeting ID.")

        response = self.client.get("/meetings/not-a-uuid/transcript")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

    def test_transcript_body_rejects_meeting_id(self) -> None:
        payload = {**self._payload(), "meeting_id": str(uuid.uuid4())}

        response = self.client.post(
            f"/meetings/{uuid.uuid4()}/transcript",
            json=payload,
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")
        self.service.create_transcript.assert_not_called()

    def test_unexpected_service_error_uses_safe_standard_response(self) -> None:
        self.service.get_transcript.side_effect = RuntimeError("database failed")

        response = self.client.get(f"/meetings/{uuid.uuid4()}/transcript")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "INTERNAL_SERVER_ERROR")
        self.assertNotIn("database failed", response.text)


if __name__ == "__main__":
    unittest.main()
