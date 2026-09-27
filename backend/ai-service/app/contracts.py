"""Provider-independent contracts for AI processing requests and results."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from shared.schemas.transcript import TranscriptSegment


class ProcessingOperation(StrEnum):
    SUMMARY = "summary"
    TASKS = "tasks"
    DECISIONS = "decisions"
    FOLLOW_UPS = "follow_ups"
    INSIGHTS = "insights"


class AgentKind(StrEnum):
    SUMMARY = "summary"
    TASK = "task"
    DECISION = "decision"
    FOLLOW_UP = "follow_up"
    INSIGHT = "insight"


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


class TranscriptContent(BaseModel):
    """Transcript data supplied to AI agents by their caller."""

    model_config = ConfigDict(extra="forbid")

    transcript_id: UUID
    language: str | None = None
    segments: list[TranscriptSegment] = Field(min_length=1)

    @field_validator("segments")
    @classmethod
    def require_nonblank_content(
        cls, segments: list[TranscriptSegment]
    ) -> list[TranscriptSegment]:
        if not any(segment.text.strip() for segment in segments):
            raise ValueError("Transcript content is required.")
        return segments


class AgentInput(BaseModel):
    """Common agent input with transcript content already retrieved."""

    model_config = ConfigDict(extra="forbid")

    meeting_id: UUID
    transcript: TranscriptContent
    meeting_context: dict[str, str] | None = None


class ModelRequest(BaseModel):
    """Provider-neutral instructions, input, and optional JSON output schema."""

    model_config = ConfigDict(extra="forbid")

    instructions: str = Field(min_length=1)
    input_text: str = Field(min_length=1)
    response_schema: dict[str, JsonValue] | None = None


class ModelResponse(BaseModel):
    """Provider-neutral raw model content; the caller validates its structure."""

    model_config = ConfigDict(extra="forbid")

    content: str


__all__ = [
    "ProcessingOperation",
    "AgentKind",
    "ProcessingRequest",
    "ProcessingResult",
    "ProcessingStatus",
    "AgentInput",
    "TranscriptContent",
    "ModelRequest",
    "ModelResponse",
]
