"""Shared OpenAPI helpers for standardized error documentation."""

from __future__ import annotations

from typing import Any

from shared.schemas.errors import ErrorBody, ErrorResponse

REQUEST_ID_HEADER = "X-Request-ID"

COMMON_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse, "description": "Bad request"},
    401: {"model": ErrorResponse, "description": "Unauthenticated"},
    403: {"model": ErrorResponse, "description": "Forbidden"},
    404: {"model": ErrorResponse, "description": "Resource not found"},
    409: {"model": ErrorResponse, "description": "Conflict"},
    422: {"model": ErrorResponse, "description": "Validation error"},
    500: {"model": ErrorResponse, "description": "Internal server error"},
    503: {"model": ErrorResponse, "description": "Service unavailable"},
}


def inject_error_schemas(openapi_schema: dict[str, Any]) -> dict[str, Any]:
    """Ensure shared error schemas are present in OpenAPI components."""
    components = openapi_schema.setdefault("components", {})
    schemas = components.setdefault("schemas", {})
    schemas["ErrorBody"] = ErrorBody.model_json_schema(ref_template="#/components/schemas/{model}")
    schemas["ErrorResponse"] = ErrorResponse.model_json_schema(ref_template="#/components/schemas/{model}")
    return openapi_schema


def inject_request_id_header(openapi_schema: dict[str, Any]) -> dict[str, Any]:
    """Document the request correlation header in OpenAPI components."""
    components = openapi_schema.setdefault("components", {})
    parameters = components.setdefault("parameters", {})
    parameters["RequestIdHeader"] = {
        "name": REQUEST_ID_HEADER,
        "in": "header",
        "required": False,
        "schema": {"type": "string"},
        "description": "Optional client-provided request correlation ID. A UUID is generated when omitted.",
    }
    return openapi_schema
