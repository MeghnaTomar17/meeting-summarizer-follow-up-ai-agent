"""
Purpose: Centralized logging configuration and helpers.
Service ownership: Shared module.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from shared.config.base import AppEnv
from shared.utils.logging_context import bind_context, get_log_context
from shared.utils.logging_formatters import DevelopmentFormatter, JsonFormatter

_CONFIGURED = False
_SERVICE_NAME = "unknown"
_SENSITIVE_LOG_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "password",
        "jwt_secret",
        "api_key",
        "openai_api_key",
        "gemini_api_key",
        "qdrant_api_key",
        "database_url",
        "redis_url",
        "celery_broker_url",
        "celery_result_backend",
    }
)
_VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


class ServiceContextFilter(logging.Filter):
    """Inject service identity and contextvars into every log record."""

    def __init__(self, service_name: str, environment: str) -> None:
        super().__init__()
        self._service_name = service_name
        self._environment = environment

    def filter(self, record: logging.LogRecord) -> bool:
        record.service = self._service_name
        record.environment = self._environment
        for key, value in get_log_context().items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True


def resolve_log_level(level_name: str) -> int:
    """Resolve a configured log level name to a logging level constant."""
    normalized = level_name.upper()
    if normalized not in _VALID_LOG_LEVELS:
        msg = f"Invalid LOG_LEVEL: {level_name!r}"
        raise ValueError(msg)
    return getattr(logging, normalized)


def configure_logging(
    *,
    service_name: str,
    log_level: str,
    app_env: AppEnv,
) -> None:
    """Configure process-wide logging once per service process."""
    global _CONFIGURED, _SERVICE_NAME

    level = resolve_log_level(log_level)
    environment = app_env.value
    _SERVICE_NAME = service_name

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.addFilter(ServiceContextFilter(service_name, environment))

    if app_env == AppEnv.PRODUCTION:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(DevelopmentFormatter())

    root_logger.addHandler(handler)

    for logger_name in _UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.setLevel(level)
        if logger_name == "uvicorn.access":
            # Application middleware owns structured request access logs.
            uvicorn_logger.setLevel(logging.WARNING)
        uvicorn_logger.propagate = True

    _CONFIGURED = True


def is_logging_configured() -> bool:
    """Return whether configure_logging() has been called in this process."""
    return _CONFIGURED


def get_logger(name: str) -> logging.Logger:
    """Return a named logger for application code."""
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    message: str,
    **fields: Any,
) -> None:
    """Emit a structured log event without encoding fields into the message."""
    extra = {"event": event, **fields}
    logger.log(level, message, extra=extra)


def is_sensitive_log_field(field_name: str) -> bool:
    """Return True when a field name must never be logged."""
    return field_name.lower() in _SENSITIVE_LOG_KEYS
