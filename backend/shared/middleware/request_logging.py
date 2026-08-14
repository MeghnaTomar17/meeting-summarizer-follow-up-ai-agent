"""
Purpose: HTTP request correlation and structured request logging middleware.
Service ownership: Shared module.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Final

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from shared.utils.logging_context import reset_log_context, set_log_context

REQUEST_ID_HEADER: Final = "X-Request-ID"
MAX_REQUEST_ID_LENGTH: Final = 128
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_HEALTH_PATHS = frozenset({"/health", "/health/live", "/health/ready"})

logger = logging.getLogger("shared.middleware.request_logging")


def resolve_request_id(header_value: str | None) -> str:
    """Reuse a valid incoming request ID or generate a new UUID."""
    if header_value is None:
        return str(uuid.uuid4())

    candidate = header_value.strip()
    if not candidate:
        return str(uuid.uuid4())
    if len(candidate) > MAX_REQUEST_ID_LENGTH:
        return str(uuid.uuid4())
    if not _REQUEST_ID_PATTERN.match(candidate):
        return str(uuid.uuid4())
    return candidate


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Attach request IDs and emit structured request completion logs."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
        token = set_log_context({"request_id": request_id})
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.exception(
                "request_failed",
                extra={
                    "event": "request_failed",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": duration_ms,
                },
            )
            raise
        else:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            response.headers[REQUEST_ID_HEADER] = request_id

            if request.url.path not in _HEALTH_PATHS:
                logger.info(
                    "request_completed",
                    extra={
                        "event": "request_completed",
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": response.status_code,
                        "duration_ms": duration_ms,
                    },
                )

            return response
        finally:
            reset_log_context(token)
