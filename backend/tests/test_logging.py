"""Phase 2.2 centralized logging tests."""

from __future__ import annotations

import importlib
import io
import json
import logging
import sys
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import PlainTextResponse

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from shared.config.base import AppEnv  # noqa: E402
from shared.middleware.request_logging import (  # noqa: E402
    REQUEST_ID_HEADER,
    RequestLoggingMiddleware,
    resolve_request_id,
)
from shared.utils.logging_context import bind_context, get_log_context  # noqa: E402
from shared.utils.logging_formatters import DevelopmentFormatter, JsonFormatter  # noqa: E402
from shared.utils.logger import (  # noqa: E402
    configure_logging,
    get_logger,
    is_sensitive_log_field,
    log_event,
    resolve_log_level,
)


def _capture_logs() -> tuple[logging.Handler, io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(DevelopmentFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    return handler, stream


def _make_record(**kwargs: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="tests.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="test message",
        args=(),
        exc_info=None,
    )
    for key, value in kwargs.items():
        setattr(record, key, value)
    return record


class LoggingTestCase(unittest.TestCase):
    def tearDown(self) -> None:
        root = logging.getLogger()
        root.handlers.clear()
        root.setLevel(logging.WARNING)

    def test_configure_logging_reads_log_level(self) -> None:
        configure_logging(
            service_name="meeting-service",
            log_level="DEBUG",
            app_env=AppEnv.DEVELOPMENT,
        )
        self.assertEqual(logging.getLogger().level, logging.DEBUG)

    def test_invalid_log_level_rejected(self) -> None:
        with self.assertRaises(ValueError):
            resolve_log_level("VERBOSE")

    def test_service_identity_in_log_records(self) -> None:
        handler, stream = _capture_logs()
        configure_logging(
            service_name="ai-service",
            log_level="INFO",
            app_env=AppEnv.DEVELOPMENT,
        )
        logging.getLogger().addHandler(handler)
        get_logger("tests.service").info("service_identity_check")
        output = stream.getvalue()
        self.assertIn("ai-service", output)

    def test_environment_in_log_records(self) -> None:
        stream = io.StringIO()
        configure_logging(
            service_name="search-service",
            log_level="INFO",
            app_env=AppEnv.TESTING,
        )
        root = logging.getLogger()
        root.handlers[0].stream = stream
        get_logger("tests.environment").info("environment_check")
        output = stream.getvalue()
        self.assertIn("testing", output)

    def test_development_formatter_readable_output(self) -> None:
        formatter = DevelopmentFormatter()
        record = _make_record(
            service="gateway-service",
            environment="development",
            event="request_completed",
            request_id="abc123",
            method="GET",
            path="/demo",
            status_code=200,
            duration_ms=4.2,
        )
        output = formatter.format(record)
        self.assertIn("INFO", output)
        self.assertIn("gateway-service", output)
        self.assertIn("request_id=abc123", output)
        self.assertIn("status_code=200", output)

    def test_production_formatter_valid_json(self) -> None:
        formatter = JsonFormatter()
        record = _make_record(
            service="worker-service",
            environment="production",
            event="request_completed",
            request_id="json-id",
        )
        payload = json.loads(formatter.format(record))
        self.assertEqual(payload["service"], "worker-service")
        self.assertEqual(payload["environment"], "production")
        self.assertEqual(payload["event"], "request_completed")
        self.assertEqual(payload["request_id"], "json-id")

    def test_request_id_generated_when_absent(self) -> None:
        generated = resolve_request_id(None)
        self.assertGreater(len(generated), 0)

    def test_existing_request_id_reused_when_valid(self) -> None:
        request_id = "client-request-id-123"
        self.assertEqual(resolve_request_id(request_id), request_id)

    def test_invalid_request_id_replaced(self) -> None:
        invalid = "a" * 200
        resolved = resolve_request_id(invalid)
        self.assertNotEqual(resolved, invalid)

    def test_request_id_returned_in_response_and_logged(self) -> None:
        app = FastAPI()
        app.add_middleware(RequestLoggingMiddleware)

        @app.get("/demo")
        async def demo() -> dict[str, str]:
            return {"ok": "true"}

        stream = io.StringIO()
        configure_logging(
            service_name="meeting-service",
            log_level="INFO",
            app_env=AppEnv.DEVELOPMENT,
        )
        root = logging.getLogger()
        root.handlers[0].stream = stream

        client = TestClient(app)
        response = client.get("/demo", headers={REQUEST_ID_HEADER: "trace-123"})
        self.assertEqual(response.headers[REQUEST_ID_HEADER], "trace-123")
        output = stream.getvalue()
        self.assertIn("request_completed", output)
        self.assertIn("request_id=trace-123", output)
        self.assertIn("path=/demo", output)
        self.assertIn("status_code=200", output)
        self.assertIn("meeting-service", output)

    def test_context_binding_and_reset(self) -> None:
        self.assertEqual(get_log_context(), {})
        with bind_context(meeting_id="m-1") as context:
            self.assertEqual(context["meeting_id"], "m-1")
            self.assertEqual(get_log_context()["meeting_id"], "m-1")
        self.assertEqual(get_log_context(), {})

    def test_health_endpoints_not_noisy_at_info(self) -> None:
        app = FastAPI()
        app.add_middleware(RequestLoggingMiddleware)

        @app.get("/health")
        async def health() -> dict[str, str]:
            return {"status": "ok"}

        handler, stream = _capture_logs()
        configure_logging(
            service_name="gateway-service",
            log_level="INFO",
            app_env=AppEnv.DEVELOPMENT,
        )
        logging.getLogger("shared.middleware.request_logging").addHandler(handler)

        client = TestClient(app)
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(stream.getvalue(), "")

    def test_exception_retains_traceback(self) -> None:
        app = FastAPI()
        app.add_middleware(RequestLoggingMiddleware)

        @app.get("/boom")
        async def boom() -> PlainTextResponse:
            raise RuntimeError("boom")

        handler, stream = _capture_logs()
        configure_logging(
            service_name="gateway-service",
            log_level="INFO",
            app_env=AppEnv.DEVELOPMENT,
        )
        logging.getLogger("shared.middleware.request_logging").addHandler(handler)

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/boom")
        self.assertEqual(response.status_code, 500)
        output = stream.getvalue()
        self.assertIn("request_failed", output)
        self.assertIn("RuntimeError", output)
        self.assertIn("Traceback", output)

    def test_sensitive_fields_not_logged_by_policy(self) -> None:
        self.assertTrue(is_sensitive_log_field("authorization"))
        self.assertTrue(is_sensitive_log_field("database_url"))
        self.assertFalse(is_sensitive_log_field("request_id"))

    def test_repeated_configure_logging_does_not_duplicate_handlers(self) -> None:
        configure_logging(
            service_name="gateway-service",
            log_level="INFO",
            app_env=AppEnv.DEVELOPMENT,
        )
        configure_logging(
            service_name="gateway-service",
            log_level="INFO",
            app_env=AppEnv.DEVELOPMENT,
        )
        self.assertEqual(len(logging.getLogger().handlers), 1)

    def test_log_event_helper(self) -> None:
        handler, stream = _capture_logs()
        configure_logging(
            service_name="ai-service",
            log_level="INFO",
            app_env=AppEnv.DEVELOPMENT,
        )
        logger = get_logger("tests.events")
        logger.addHandler(handler)
        log_event(logger, logging.INFO, "demo_event", "demo message", meeting_id="m-99")
        output = stream.getvalue()
        self.assertIn("event=demo_event", output)
        self.assertIn("meeting_id=m-99", output)

    def test_all_services_import_shared_logger(self) -> None:
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
