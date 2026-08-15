"""
Purpose: Gateway OpenAPI customization for the public API contract.
Service ownership: gateway-service.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from shared.api.openapi import inject_error_schemas, inject_request_id_header

API_VERSION = "v1"
PUBLIC_API_DESCRIPTION = (
    "Public REST API for the MannerAI Meetings Platform. "
    "All business endpoints are versioned under /api/v1. "
    "Clients may supply X-Request-ID for request correlation; "
    "the header is echoed on every response."
)


def configure_gateway_openapi(app: FastAPI) -> None:
    """Attach the canonical public OpenAPI schema generator to the gateway app."""

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema

        openapi_schema = get_openapi(
            title="MannerAI Meetings Platform API",
            version=app.version,
            description=PUBLIC_API_DESCRIPTION,
            routes=app.routes,
            tags=app.openapi_tags,
            servers=app.servers,
        )
        openapi_schema["info"]["x-api-version"] = API_VERSION
        inject_error_schemas(openapi_schema)
        inject_request_id_header(openapi_schema)
        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi  # type: ignore[method-assign]
