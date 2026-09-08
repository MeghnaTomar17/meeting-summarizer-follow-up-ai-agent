"""Phase 2.4 API design and contract standardization tests."""

from __future__ import annotations

import ast
import importlib
import sys
import unittest
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
GATEWAY_ROOT = BACKEND_ROOT / "gateway-service"
SERVICE_NAMES = (
    "gateway-service",
    "meeting-service",
    "ai-service",
    "search-service",
    "worker-service",
)


def _clear_service_modules() -> None:
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]


def _clear_service_paths() -> None:
    for service_name in SERVICE_NAMES:
        service_root = str(BACKEND_ROOT / service_name)
        while service_root in sys.path:
            sys.path.remove(service_root)


def _load_gateway_app() -> FastAPI:
    _clear_service_modules()
    _clear_service_paths()
    sys.path.insert(0, str(GATEWAY_ROOT))
    gateway_main = importlib.import_module("app.main")
    gateway_main.app.openapi_schema = None
    return gateway_main.app


class ApiDesignTestCase(unittest.TestCase):
    def setUp(self) -> None:
        from shared.config.base import AppEnv
        from shared.utils.logger import configure_logging

        configure_logging(
            service_name="gateway-service",
            log_level="INFO",
            app_env=AppEnv.DEVELOPMENT,
        )
        self.gateway_app = _load_gateway_app()
        self.client = TestClient(self.gateway_app, raise_server_exceptions=False)

    def test_api_v1_prefix_constant(self) -> None:
        from shared.api.constants import API_V1_PREFIX

        self.assertEqual(API_V1_PREFIX, "/api/v1")

    def test_future_routers_mount_under_api_v1(self) -> None:
        from app.api.v1.router import api_v1_router

        self.assertEqual(api_v1_router.prefix, "/api/v1")
        child = APIRouter()

        @child.get("/example")
        async def example() -> dict[str, str]:
            return {"status": "ok"}

        parent = APIRouter(prefix="/api/v1")
        parent.include_router(child, prefix="/meetings")
        route_paths = [route.path for route in parent.routes]
        self.assertIn("/api/v1/meetings/example", route_paths)

    def test_health_endpoints_outside_api_v1(self) -> None:
        for path in ("/health", "/health/live", "/health/ready"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertEqual(response.json()["status"], "ok")

        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 404)

    def test_pagination_defaults(self) -> None:
        from shared.schemas.pagination import PaginationParams

        params = PaginationParams()
        self.assertEqual(params.page, 1)
        self.assertEqual(params.page_size, 20)

    def test_page_size_maximum_enforced(self) -> None:
        from pydantic import ValidationError
        from shared.schemas.pagination import PaginationParams

        with self.assertRaises(ValidationError):
            PaginationParams(page_size=101)

    def test_invalid_page_values_rejected(self) -> None:
        from pydantic import ValidationError
        from shared.schemas.pagination import PaginationParams

        with self.assertRaises(ValidationError):
            PaginationParams(page=0)

        with self.assertRaises(ValidationError):
            PaginationParams(page_size=0)

    def test_paginated_response_serializes(self) -> None:
        from shared.schemas.meeting import MeetingPublic, MeetingStatus
        from shared.schemas.pagination import build_paginated_response
        from shared.utils.helpers import utc_now

        now = utc_now()
        meeting = MeetingPublic(
            id="m-1",
            title="Weekly sync",
            status=MeetingStatus.READY,
            created_at=now,
            updated_at=now,
        )
        response = build_paginated_response(
            [meeting],
            page=1,
            page_size=20,
            total=1,
        )
        payload = response.model_dump(mode="json")
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["pagination"]["page"], 1)
        self.assertEqual(payload["pagination"]["page_size"], 20)
        self.assertEqual(payload["pagination"]["total"], 1)
        self.assertEqual(payload["pagination"]["total_pages"], 1)

    def test_user_public_excludes_password_hash(self) -> None:
        user_schema_path = BACKEND_ROOT / "shared" / "schemas" / "user.py"
        module = ast.parse(user_schema_path.read_text(encoding="utf-8"))
        class_fields: dict[str, set[str]] = {}
        for node in module.body:
            if isinstance(node, ast.ClassDef):
                fields = {
                    assignment.target.id
                    for assignment in node.body
                    if isinstance(assignment, ast.AnnAssign)
                    and isinstance(assignment.target, ast.Name)
                }
                class_fields[node.name] = fields

        self.assertIn("password_hash", class_fields["UserInDB"])
        self.assertNotIn("password_hash", class_fields["UserPublic"])

    def test_meeting_public_excludes_internal_fields(self) -> None:
        from shared.schemas.meeting import MeetingInDB, MeetingPublic

        self.assertIn("organization_id", MeetingInDB.model_fields)
        self.assertIn("created_by", MeetingInDB.model_fields)
        self.assertNotIn("organization_id", MeetingPublic.model_fields)
        self.assertNotIn("created_by", MeetingPublic.model_fields)

    def test_gateway_openapi_accessible(self) -> None:
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("openapi", response.json())

    def test_gateway_openapi_metadata(self) -> None:
        schema = self.gateway_app.openapi()
        self.assertEqual(schema["info"]["title"], "MannerAI Meetings Platform API")
        self.assertEqual(schema["info"]["version"], "0.1.0")
        self.assertEqual(schema["info"]["x-api-version"], "v1")
        server_urls = [server["url"] for server in schema["servers"]]
        self.assertIn("/api/v1", server_urls)
        tag_names = {tag["name"] for tag in schema["tags"]}
        for expected in ("auth", "users", "meetings", "search", "analytics", "integrations"):
            self.assertIn(expected, tag_names)

    def test_error_response_in_openapi_components(self) -> None:
        schema = self.gateway_app.openapi()
        components = schema["components"]["schemas"]
        self.assertIn("ErrorResponse", components)
        self.assertIn("ErrorBody", components)

    def test_request_id_documented_in_openapi(self) -> None:
        schema = self.gateway_app.openapi()
        parameters = schema["components"]["parameters"]
        self.assertIn("RequestIdHeader", parameters)
        self.assertEqual(parameters["RequestIdHeader"]["name"], "X-Request-ID")

    def test_unmatched_route_returns_standard_error_envelope(self) -> None:
        response = self.client.get("/does-not-exist-route")
        body = response.json()
        self.assertEqual(response.status_code, 404)
        self.assertEqual(body["error"]["code"], "NOT_FOUND")
        self.assertEqual(body["error"]["message"], "Resource not found.")
        self.assertIn("request_id", body["error"])
        self.assertNotIn("detail", body)

    def test_unmatched_route_under_api_v1(self) -> None:
        response = self.client.get("/api/v1/does-not-exist")
        body = response.json()
        self.assertEqual(response.status_code, 404)
        self.assertEqual(body["error"]["code"], "NOT_FOUND")
        self.assertEqual(body["error"]["message"], "Resource not found.")

    def test_unmatched_route_includes_request_id_header(self) -> None:
        response = self.client.get(
            "/missing",
            headers={"X-Request-ID": "trace-unmatched"},
        )
        self.assertEqual(response.headers["X-Request-ID"], "trace-unmatched")
        self.assertEqual(response.json()["error"]["request_id"], "trace-unmatched")


class ServiceImportTestCase(unittest.TestCase):
    def test_all_services_import_correctly(self) -> None:
        for service_name in SERVICE_NAMES:
            _clear_service_modules()
            _clear_service_paths()
            sys.path.insert(0, str(BACKEND_ROOT / service_name))
            main_module = importlib.import_module("app.main")
            self.assertIsNotNone(main_module.app)


if __name__ == "__main__":
    unittest.main()
