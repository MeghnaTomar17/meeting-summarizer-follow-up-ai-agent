"""
Purpose: JWT validation and request user context middleware.
Future responsibilities: Extract claims, attach User to request.state.
Service ownership: gateway-service.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class AuthMiddleware(BaseHTTPMiddleware):
    """Placeholder auth middleware — TODO: implement JWT verification."""

    async def dispatch(self, request: Request, call_next: object) -> Response:
        # TODO: skip public paths; validate Authorization header
        return await call_next(request)  # type: ignore[misc]
