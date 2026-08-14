"""
Purpose: Logging formatters for development and production output.
Service ownership: Shared module.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from shared.utils.logging_context import CONTEXT_FIELD_NAMES


def _structured_fields(record: logging.LogRecord) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for key in CONTEXT_FIELD_NAMES:
        if hasattr(record, key):
            value = getattr(record, key)
            if value is not None:
                fields[key] = value
    return fields


class DevelopmentFormatter(logging.Formatter):
    """Human-readable console formatter for development and testing."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
            timespec="seconds"
        )
        service = getattr(record, "service", "unknown")
        environment = getattr(record, "environment", "unknown")
        message = record.getMessage()
        parts = [
            timestamp,
            record.levelname,
            service,
            environment,
            message,
        ]
        fields = _structured_fields(record)
        if fields:
            field_text = " ".join(f"{key}={value}" for key, value in fields.items())
            parts.append(field_text)
        line = " ".join(parts)
        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        return line


class JsonFormatter(logging.Formatter):
    """JSON structured formatter for production logs."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "service": getattr(record, "service", "unknown"),
            "environment": getattr(record, "environment", "unknown"),
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(_structured_fields(record))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)
