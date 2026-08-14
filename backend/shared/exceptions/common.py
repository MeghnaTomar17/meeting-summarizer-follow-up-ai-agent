"""
Purpose: Common HTTP-level application exceptions.
Service ownership: Shared module.
"""

from __future__ import annotations

from typing import Any

from shared.exceptions.base import AppError


class BadRequestError(AppError):
    def __init__(
        self,
        message: str = "Bad request.",
        *,
        code: str = "BAD_REQUEST",
        details: list[Any] | dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, http_status=400, details=details)


class UnauthorizedError(AppError):
    def __init__(
        self,
        message: str = "Not authenticated.",
        *,
        code: str = "UNAUTHORIZED",
        details: list[Any] | dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, http_status=401, details=details)


class ForbiddenError(AppError):
    def __init__(
        self,
        message: str = "Forbidden.",
        *,
        code: str = "FORBIDDEN",
        details: list[Any] | dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, http_status=403, details=details)


class NotFoundError(AppError):
    def __init__(
        self,
        message: str = "Resource not found.",
        *,
        code: str = "NOT_FOUND",
        details: list[Any] | dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, http_status=404, details=details)


class ConflictError(AppError):
    def __init__(
        self,
        message: str = "Conflict.",
        *,
        code: str = "CONFLICT",
        details: list[Any] | dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, http_status=409, details=details)


class ValidationError(AppError):
    def __init__(
        self,
        message: str = "Validation failed.",
        *,
        code: str = "VALIDATION_ERROR",
        details: list[Any] | dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, http_status=422, details=details)


class ServiceUnavailableError(AppError):
    def __init__(
        self,
        message: str = "Service unavailable.",
        *,
        code: str = "SERVICE_UNAVAILABLE",
        details: list[Any] | dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, http_status=503, details=details)
