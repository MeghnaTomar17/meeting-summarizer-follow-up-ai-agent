"""Standardized API error response schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str
    details: list[Any] | dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
