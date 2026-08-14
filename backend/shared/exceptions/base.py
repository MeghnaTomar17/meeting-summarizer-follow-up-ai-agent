"""
Purpose: Base application exception independent of FastAPI.
Service ownership: Shared module.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base application error with HTTP-agnostic semantics."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "INTERNAL_SERVER_ERROR",
        http_status: int = 500,
        details: list[Any] | dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        self.code = code
        self.http_status = http_status
        self.details = details
        super().__init__(message)
