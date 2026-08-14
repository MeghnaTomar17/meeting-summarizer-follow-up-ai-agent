"""
Purpose: Shared service startup helpers for logging.
Service ownership: Shared module.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from shared.middleware.request_logging import RequestLoggingMiddleware
from shared.exceptions.handlers import register_exception_handlers as _register_exception_handlers
from shared.utils.logger import configure_logging


def init_service_logging(get_settings: Callable[[], Any]) -> None:
    """Initialize centralized logging for a service process."""
    settings = get_settings()
    configure_logging(
        service_name=settings.service_name,
        log_level=settings.log_level,
        app_env=settings.app_env,
    )


def register_logging_middleware(app: FastAPI) -> None:
    """Attach shared request logging middleware to a FastAPI app."""
    app.add_middleware(RequestLoggingMiddleware)


def register_exception_handlers(app: FastAPI) -> None:
    """Attach shared exception handlers to a FastAPI app."""
    _register_exception_handlers(app)
