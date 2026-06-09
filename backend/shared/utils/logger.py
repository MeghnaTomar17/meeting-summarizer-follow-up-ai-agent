"""
Purpose: Structured logging configuration.
Future responsibilities: JSON logs, correlation IDs, OpenTelemetry hooks.
Service ownership: Shared module.
"""

from __future__ import annotations

import logging
import sys
from typing import Any


def configure_logging(level: str = "INFO") -> None:
    """Configure root logger — TODO: structlog or loguru integration."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )


def get_logger(name: str) -> logging.Logger:
    """Return named logger for DI-friendly usage."""
    return logging.getLogger(name)


def bind_context(**kwargs: Any) -> dict[str, Any]:
    """Placeholder for request-scoped log context — TODO: implement."""
    return kwargs
