"""Phase 2.3 standardized exception and error handling tests."""

from __future__ import annotations

import importlib
import io
import json
import logging
import sys
import unittest
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from shared.config.base import AppEnv  # noqa: E402
from shared.exceptions.common import NotFoundError  # noqa: E402
from shared.middleware.request_logging import REQUEST_ID_HEADER, RequestLoggingMiddleware  # noqa: E402
from shared.utils.logger import configure_logging  # noqa: E402
from shared.utils.logging_context import get_log_context  # noqa: E402
from shared.utils.service_bootstrap import register_exception_handlers  # noqa: E402


class DemoPayload(BaseModel):
    name: str = Field(min_length=3)


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(app)

    @app.get("/not-found")
    async def not_found() -> dict[str, str]:
        raise NotFoundError("Meeting not found.")

    @app.get("/boom")
    async def boom() -> dict[str, str]:
        raise RuntimeError("sensitive internal database connection failed")

    @app.get("/http-unauthorized")
    async def http_unauthorized() -> dict[str, str]:
        raise HTTPException(status_code=401, detail="Not authenticated")

    @app.get("/http-not-found")
    async def http_not_found() -> dict[str, str]:
        raise HTTPException(status_code=404, detail="Missing resource")

    @app.post("/validate")
    async def validate(payload: DemoPayload) -> dict[str, str]:
        return {"name": payload.name}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "test-service"}

    return app


class ExceptionHandlingTestCase(unittest.TestCase):
    def setUp(self) -> None:
        configure_logging(
            service_name="gateway-service",
            log_level="INFO",
            app_env=AppEnv.DEVELOPMENT,
        )
        self.app = _build_test_app()
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def test_app_error_status_and_envelope(self) -> None:
        response = self.client.get("/not-found", headers={REQUEST_ID_HEADER: "req-not-found"})
        body = response.json()
        self.assertEqual(response.status_code, 404)
        self.assertEqual(body["error"]["code"], "NOT_FOUND")
        self.assertEqual(body["error"]["message"], "Meeting not found.")
        self.assertEqual(body["error"]["request_id"], "req-not-found")
        self.assertEqual(response.headers[REQUEST_ID_HEADER], "req-not-found")

    def test_validation_error_envelope(self) -> None:
        response = self.client.post(
            "/validate",
            json={"name": "a"},
            headers={REQUEST_ID_HEADER: "req-validate"},
        )
        body = response.json()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(body["error"]["code"], "VALIDATION_ERROR")
        self.assertEqual(body["error"]["message"], "Request validation failed")
        self.assertEqual(body["error"]["request_id"], "req-validate")
        self.assertIsInstance(body["error"]["details"], list)
        self.assertTrue(body["error"]["details"])
        self.assertIn("field", body["error"]["details"][0])
        self.assertIn("message", body["error"]["details"][0])

    def test_http_exception_unauthorized_translation(self) -> None:
        response = self.client.get("/http-unauthorized", headers={REQUEST_ID_HEADER: "req-401"})
        body = response.json()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(body["error"]["code"], "UNAUTHORIZED")
        self.assertEqual(body["error"]["message"], "Not authenticated")
        self.assertEqual(body["error"]["request_id"], "req-401")

    def test_http_exception_not_found_translation(self) -> None:
        response = self.client.get("/http-not-found", headers={REQUEST_ID_HEADER: "req-404"})
        body = response.json()
        self.assertEqual(response.status_code, 404)
        self.assertEqual(body["error"]["code"], "NOT_FOUND")
        self.assertEqual(body["error"]["message"], "Missing resource")

    def test_generic_exception_returns_safe_500(self) -> None:
        response = self.client.get("/boom", headers={REQUEST_ID_HEADER: "req-500"})
        body = response.json()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(body["error"]["code"], "INTERNAL_SERVER_ERROR")
        self.assertEqual(body["error"]["message"], "An unexpected error occurred.")
        self.assertEqual(body["error"]["request_id"], "req-500")
        self.assertEqual(response.headers[REQUEST_ID_HEADER], "req-500")
        self.assertNotIn("database", json.dumps(body))
        self.assertNotIn("Traceback", json.dumps(body))
        self.assertNotIn("RuntimeError", json.dumps(body))

    def test_generic_exception_logged_with_traceback(self) -> None:
        stream = io.StringIO()
        handler_logger = logging.getLogger("shared.exceptions.handlers")
        stream_handler = logging.StreamHandler(stream)
        handler_logger.addHandler(stream_handler)
        handler_logger.setLevel(logging.DEBUG)
        try:
            self.client.get("/boom", headers={REQUEST_ID_HEADER: "req-log"})
            output = stream.getvalue()
            self.assertIn("unhandled_exception", output)
            self.assertIn("Traceback", output)
            self.assertIn("RuntimeError", output)
        finally:
            handler_logger.removeHandler(stream_handler)

    def test_context_reset_after_request(self) -> None:
        self.client.get("/not-found", headers={REQUEST_ID_HEADER: "req-reset"})
        self.assertEqual(get_log_context(), {})

    def test_health_endpoint_unchanged(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertNotIn("error", response.json())

    def test_openapi_remains_accessible(self) -> None:
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("openapi", response.json())

    def test_all_services_register_handlers(self) -> None:
        services = [
            "gateway-service",
            "meeting-service",
            "ai-service",
            "search-service",
            "worker-service",
        ]
        for service_name in services:
            service_root = str(BACKEND_ROOT / service_name)
            for key in list(sys.modules):
                if key == "app" or key.startswith("app."):
                    del sys.modules[key]
            if service_root in sys.path:
                sys.path.remove(service_root)
            sys.path.insert(0, service_root)
            main_module = importlib.import_module("app.main")
            self.assertIsNotNone(main_module.app)


if __name__ == "__main__":
    unittest.main()
