"""
Purpose: Centralized FastAPI exception handlers.
Service ownership: Shared module.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse

from shared.exceptions.base import AppError
from shared.middleware.request_logging import REQUEST_ID_HEADER
from shared.schemas.errors import ErrorBody, ErrorResponse
from shared.utils.logging_context import get_log_context

logger = logging.getLogger("shared.exceptions.handlers")

_STATUS_TO_CODE: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    503: "SERVICE_UNAVAILABLE",
}

_GENERIC_INTERNAL_MESSAGE = "An unexpected error occurred."


def _resolve_request_id(request: Request) -> str:
    context_id = get_log_context().get("request_id")
    if isinstance(context_id, str) and context_id:
        return context_id
    state_id = getattr(request.state, "request_id", None)
    if isinstance(state_id, str) and state_id:
        return state_id
    return "unknown"


def _build_error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    request_id: str,
    details: list[Any] | dict[str, Any] | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            request_id=request_id,
            details=details,
        )
    )
    response = JSONResponse(
        status_code=status_code,
        content=payload.model_dump(exclude_none=True),
    )
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


def _http_exception_message(detail: Any) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list) and detail:
        first = detail[0]
        if isinstance(first, dict):
            msg = first.get("msg")
            if isinstance(msg, str):
                return msg
        return "Request failed."
    return "Request failed."


def _normalize_validation_errors(exc: RequestValidationError) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for error in exc.errors():
        location = error.get("loc", ())
        field = ".".join(str(part) for part in location if part != "body")
        if not field and location:
            field = ".".join(str(part) for part in location)
        normalized.append(
            {
                "field": field,
                "message": str(error.get("msg", "Invalid value")),
                "type": str(error.get("type", "validation_error")),
            }
        )
    return normalized


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    request_id = _resolve_request_id(request)
    if exc.http_status >= 500:
        logger.warning(
            "application_error",
            extra={
                "event": "application_error",
                "request_id": request_id,
                "error_code": exc.code,
                "http_status": exc.http_status,
            },
        )
    else:
        logger.info(
            "application_error",
            extra={
                "event": "application_error",
                "request_id": request_id,
                "error_code": exc.code,
                "http_status": exc.http_status,
            },
        )
    return _build_error_response(
        status_code=exc.http_status,
        code=exc.code,
        message=exc.message,
        request_id=request_id,
        details=exc.details,
    )


async def request_validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    request_id = _resolve_request_id(request)
    details = _normalize_validation_errors(exc)
    logger.info(
        "validation_error",
        extra={
            "event": "validation_error",
            "request_id": request_id,
            "error_count": len(details),
        },
    )
    return _build_error_response(
        status_code=422,
        code="VALIDATION_ERROR",
        message="Request validation failed",
        request_id=request_id,
        details=details,
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    request_id = _resolve_request_id(request)
    code = _STATUS_TO_CODE.get(exc.status_code, f"HTTP_ERROR_{exc.status_code}")
    message = _http_exception_message(exc.detail)
    logger.info(
        "http_exception",
        extra={
            "event": "http_exception",
            "request_id": request_id,
            "error_code": code,
            "http_status": exc.status_code,
        },
    )
    details = exc.detail if isinstance(exc.detail, (list, dict)) else None
    return _build_error_response(
        status_code=exc.status_code,
        code=code,
        message=message,
        request_id=request_id,
        details=details,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = _resolve_request_id(request)
    logger.exception(
        "unhandled_exception",
        extra={
            "event": "unhandled_exception",
            "request_id": request_id,
            "exception_type": type(exc).__name__,
        },
    )
    return _build_error_response(
        status_code=500,
        code="INTERNAL_SERVER_ERROR",
        message=_GENERIC_INTERNAL_MESSAGE,
        request_id=request_id,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register shared exception handlers on a FastAPI application."""
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
