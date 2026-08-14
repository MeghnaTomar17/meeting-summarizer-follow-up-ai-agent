"""Shared application exception hierarchy."""

from shared.exceptions.base import AppError
from shared.exceptions.common import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    UnauthorizedError,
    ValidationError,
)
from shared.exceptions.handlers import register_exception_handlers

__all__ = [
    "AppError",
    "BadRequestError",
    "ConflictError",
    "ForbiddenError",
    "NotFoundError",
    "ServiceUnavailableError",
    "UnauthorizedError",
    "ValidationError",
    "register_exception_handlers",
]
