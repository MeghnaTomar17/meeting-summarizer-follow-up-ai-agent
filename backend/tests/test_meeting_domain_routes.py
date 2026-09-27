"""API contract tests for Phase 5 meeting result resources."""

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


def _load_app() -> FastAPI:
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]
    sys.path.insert(0, str(MEETING_ROOT))
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    return importlib.import_module("app.main").app


class MeetingDomainRoutesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.app = _load_app()
        auth = importlib.import_module("app.auth.dependencies")
        self.user_id = uuid.uuid4()
        self.app.dependency_overrides[auth.get_authenticated_user_id] = lambda: self.user_id
        self.services = {}
        def provide(target):
            async def dependency():
                return target
            return dependency

        routes = {
            "summary": ("app.routes.summaries", "get_summary_service"),
            "task": ("app.routes.tasks", "get_task_service"),
            "decision": ("app.routes.decisions", "get_decision_service"),
            "followup": ("app.routes.followups", "get_followup_service"),
        }
        for name, (module_name, dependency_name) in routes.items():
            dependency = getattr(importlib.import_module(module_name), dependency_name)
            service = MagicMock()
            for method in ("create_summary", "get_summary", "list_summaries", "get_latest_summary", "create_task", "get_task", "list_tasks", "update_task", "create_decision", "get_decision", "list_decisions", "create_followup", "get_followup", "list_followups", "update_followup"):
                setattr(service, method, AsyncMock())
            self.services[name] = service
            self.app.dependency_overrides[dependency] = provide(service)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def tearDown(self) -> None:
        self.client.close()
        self.app.dependency_overrides.clear()

    @staticmethod
    def _dto(schema: str, meeting_id: str):
        now = datetime.now(timezone.utc)
        common = {"id": str(uuid.uuid4()), "meeting_id": meeting_id}
        if schema == "summary":
            from shared.schemas.summary import SummaryInDB
            return SummaryInDB(**common, content="Summary", key_topics=[], version=1, created_at=now)
        if schema == "task":
            from shared.schemas.task import TaskInDB
            return TaskInDB(**common, title="Ship", status="open", created_at=now, updated_at=now)
        if schema == "decision":
            from shared.schemas.decision import DecisionInDB
            return DecisionInDB(**common, statement="Ship", participants=[], created_at=now)
        from shared.schemas.followup import FollowupInDB
        return FollowupInDB(**common, subject="Next", body_html="<p>Next</p>", recipients=["a@example.com"], created_at=now)

    def test_summary_create_uses_path_parent_and_latest_precedes_id_route(self) -> None:
        meeting_id = str(uuid.uuid4())
        dto = self._dto("summary", meeting_id)
        self.services["summary"].create_summary.return_value = dto
        response = self.client.post(f"/meetings/{meeting_id}/summaries", json={"content": "Summary"})
        self.assertEqual(response.status_code, 201)
        payload, user_id = self.services["summary"].create_summary.await_args.args
        self.assertEqual(payload.meeting_id, meeting_id)
        self.assertEqual(user_id, self.user_id)
        self.services["summary"].get_latest_summary.return_value = dto
        self.assertEqual(self.client.get(f"/meetings/{meeting_id}/summaries/latest").status_code, 200)

    def test_summary_list_get_missing_and_conflict_use_standard_errors(self) -> None:
        from shared.exceptions.common import ConflictError, NotFoundError
        meeting_id = str(uuid.uuid4())
        self.services["summary"].list_summaries.return_value = []
        self.assertEqual(self.client.get(f"/meetings/{meeting_id}/summaries").json()["items"], [])
        self.services["summary"].get_summary.side_effect = NotFoundError("Summary not found.")
        self.assertEqual(self.client.get(f"/meetings/{meeting_id}/summaries/{uuid.uuid4()}").status_code, 404)
        self.services["summary"].create_summary.side_effect = ConflictError("Duplicate version.")
        self.assertEqual(self.client.post(f"/meetings/{meeting_id}/summaries", json={"content": "x"}).status_code, 409)

    def test_task_create_list_filter_get_and_patch(self) -> None:
        meeting_id = str(uuid.uuid4())
        dto = self._dto("task", meeting_id)
        self.services["task"].create_task.return_value = dto
        response = self.client.post(f"/meetings/{meeting_id}/tasks", json={"title": "Ship"})
        self.assertEqual(response.status_code, 201)
        self.services["task"].list_tasks.return_value = [dto]
        self.assertEqual(self.client.get(f"/meetings/{meeting_id}/tasks?status=open").status_code, 200)
        self.assertEqual(self.services["task"].list_tasks.await_args.kwargs["status"].value, "open")
        self.services["task"].get_task.return_value = dto
        self.assertEqual(self.client.get(f"/meetings/{meeting_id}/tasks/{dto.id}").status_code, 200)
        self.services["task"].update_task.return_value = dto
        self.assertEqual(self.client.patch(f"/meetings/{meeting_id}/tasks/{dto.id}", json={"title": "Ship now"}).status_code, 200)

    def test_task_missing_cross_parent_and_cross_user_forbidden(self) -> None:
        from shared.exceptions.common import ForbiddenError, NotFoundError
        meeting_id = str(uuid.uuid4())
        self.services["task"].get_task.side_effect = NotFoundError("Task not found.")
        self.assertEqual(self.client.get(f"/meetings/{meeting_id}/tasks/{uuid.uuid4()}").status_code, 404)
        dto = self._dto("task", str(uuid.uuid4()))
        self.services["task"].get_task.side_effect = None
        self.services["task"].get_task.return_value = dto
        self.assertEqual(self.client.get(f"/meetings/{meeting_id}/tasks/{dto.id}").status_code, 404)
        self.services["task"].create_task.side_effect = ForbiddenError()
        self.assertEqual(self.client.post(f"/meetings/{meeting_id}/tasks", json={"title": "x"}).status_code, 403)

    def test_mismatched_parent_does_not_update_task(self) -> None:
        meeting_id = str(uuid.uuid4())
        dto = self._dto("task", str(uuid.uuid4()))
        self.services["task"].get_task.return_value = dto
        response = self.client.patch(f"/meetings/{meeting_id}/tasks/{dto.id}", json={"title": "mutate"})
        self.assertEqual(response.status_code, 404)
        self.services["task"].update_task.assert_not_awaited()

    def test_decision_create_list_get_and_missing(self) -> None:
        from shared.exceptions.common import NotFoundError
        meeting_id = str(uuid.uuid4())
        dto = self._dto("decision", meeting_id)
        self.services["decision"].create_decision.return_value = dto
        self.assertEqual(self.client.post(f"/meetings/{meeting_id}/decisions", json={"statement": "Ship"}).status_code, 201)
        self.services["decision"].list_decisions.return_value = [dto]
        self.assertEqual(self.client.get(f"/meetings/{meeting_id}/decisions").status_code, 200)
        self.services["decision"].get_decision.return_value = dto
        self.assertEqual(self.client.get(f"/meetings/{meeting_id}/decisions/{dto.id}").status_code, 200)
        self.services["decision"].get_decision.side_effect = NotFoundError("Decision not found.")
        self.assertEqual(self.client.get(f"/meetings/{meeting_id}/decisions/{uuid.uuid4()}").status_code, 404)

    def test_followup_create_list_filter_get_and_patch(self) -> None:
        meeting_id = str(uuid.uuid4())
        dto = self._dto("followup", meeting_id)
        self.services["followup"].create_followup.return_value = dto
        body = {"subject": "Next", "body_html": "<p>Next</p>", "recipients": ["a@example.com"]}
        self.assertEqual(self.client.post(f"/meetings/{meeting_id}/followups", json=body).status_code, 201)
        self.services["followup"].list_followups.return_value = [dto]
        self.assertEqual(self.client.get(f"/meetings/{meeting_id}/followups?status=draft").status_code, 200)
        self.assertEqual(self.services["followup"].list_followups.await_args.kwargs["status"].value, "draft")
        self.services["followup"].get_followup.return_value = dto
        self.assertEqual(self.client.get(f"/meetings/{meeting_id}/followups/{dto.id}").status_code, 200)
        self.services["followup"].update_followup.return_value = dto
        self.assertEqual(self.client.patch(f"/meetings/{meeting_id}/followups/{dto.id}", json={"subject": "Updated"}).status_code, 200)

    def test_followup_missing_and_forbidden_access(self) -> None:
        from shared.exceptions.common import ForbiddenError, NotFoundError
        meeting_id = str(uuid.uuid4())
        self.services["followup"].get_followup.side_effect = NotFoundError("Follow-up not found.")
        self.assertEqual(self.client.get(f"/meetings/{meeting_id}/followups/{uuid.uuid4()}").status_code, 404)
        self.services["followup"].create_followup.side_effect = ForbiddenError()
        body = {"subject": "Next", "body_html": "<p>Next</p>", "recipients": ["a@example.com"]}
        self.assertEqual(self.client.post(f"/meetings/{meeting_id}/followups", json=body).status_code, 403)


if __name__ == "__main__":
    unittest.main()
