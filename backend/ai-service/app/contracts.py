"""Provider-independent contracts for AI processing requests and results."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class ProcessingOperation(StrEnum):
    SUMMARY = "summary"
    TASKS = "tasks"
    DECISIONS = "decisions"
    FOLLOW_UPS = "follow_ups"
    INSIGHTS = "insights"


class ProcessingStatus(StrEnum):
    NOT_IMPLEMENTED = "not_implemented"


class ProcessingRequest(BaseModel):
    """Identify a meeting transcript and the processing sections requested."""

    model_config = ConfigDict(extra="forbid")

    meeting_id: UUID
    transcript_id: UUID
    requested_operations: list[ProcessingOperation] = Field(min_length=1)
    context: dict[str, str] | None = None


class ProcessingResult(BaseModel):
    """Structured handoff; empty sections are explicit until agents exist."""

    meeting_id: UUID
    transcript_id: UUID
    requested_operations: list[ProcessingOperation]
    status: ProcessingStatus
    sections: dict[ProcessingOperation, JsonValue] = Field(default_factory=dict)


__all__ = [
    "ProcessingOperation",
    "ProcessingRequest",
    "ProcessingResult",
    "ProcessingStatus",
]
