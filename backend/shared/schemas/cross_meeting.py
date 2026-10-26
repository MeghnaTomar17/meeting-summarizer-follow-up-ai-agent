"""Typed, bounded structured evidence for cross-meeting intelligence."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from shared.api.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from shared.schemas.meeting_insight import InsightCategory
from shared.schemas.pagination import PaginatedResponse
from shared.schemas.semantic_search import SemanticSearchRequest, SemanticSearchResponse
from shared.schemas.task import TaskStatus


class StructuredTaskFilter(str, Enum):
    ALL = "all"
    UNRESOLVED = "unresolved"
    OVERDUE = "overdue"


class CrossMeetingDataQuery(BaseModel):
    """Bounded selection options; identity is always supplied by trusted auth."""

    model_config = ConfigDict(extra="forbid")

    since: datetime | None = None
    until: datetime | None = None
    task_filter: StructuredTaskFilter = StructuredTaskFilter.ALL
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)

    @field_validator("since", "until")
    @classmethod
    def require_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("Time filters must include a timezone.")
        return value

    @model_validator(mode="after")
    def validate_time_window(self) -> CrossMeetingDataQuery:
        if self.since is not None and self.until is not None and self.since >= self.until:
            raise ValueError("since must be earlier than until.")
        return self


class CrossMeetingRecord(BaseModel):
    id: UUID
    title: str
    description: str | None
    scheduled_at: datetime | None
    created_at: datetime


class CrossMeetingTaskRecord(BaseModel):
    id: UUID
    meeting_id: UUID
    title: str
    description: str | None
    status: TaskStatus
    due_at: datetime | None
    created_at: datetime


class CrossMeetingDecisionRecord(BaseModel):
    id: UUID
    meeting_id: UUID
    statement: str
    context: str | None
    participants: list[str]
    created_at: datetime


class CrossMeetingInsightRecord(BaseModel):
    id: UUID
    meeting_id: UUID
    category: InsightCategory
    title: str
    description: str
    created_at: datetime


class CrossMeetingStructuredData(BaseModel):
    """Separate bounded, stable pages for each structured evidence type."""

    meetings: PaginatedResponse[CrossMeetingRecord]
    tasks: PaginatedResponse[CrossMeetingTaskRecord]
    decisions: PaginatedResponse[CrossMeetingDecisionRecord]
    insights: PaginatedResponse[CrossMeetingInsightRecord]


class CrossMeetingEvidenceRequest(BaseModel):
    """Compose existing bounded query contracts without accepting identity."""

    model_config = ConfigDict(extra="forbid")

    semantic: SemanticSearchRequest
    structured: CrossMeetingDataQuery


class CrossMeetingEvidenceBundle(BaseModel):
    """Validated structured and transcript evidence; never an answer."""

    structured: CrossMeetingStructuredData
    semantic: SemanticSearchResponse


class CrossMeetingQuestionRequest(BaseModel):
    """Question and bounded retrieval options; authenticated identity is external."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=10, ge=1, le=50)
    structured: CrossMeetingDataQuery = Field(default_factory=CrossMeetingDataQuery)

    @field_validator("question")
    @classmethod
    def require_nonblank_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Question must not be blank.")
        return value


class CrossMeetingCitationType(str, Enum):
    MEETING = "meeting"
    TASK = "task"
    DECISION = "decision"
    INSIGHT = "insight"
    TRANSCRIPT_CHUNK = "transcript_chunk"


class CrossMeetingCitation(BaseModel):
    """Citation metadata copied from trusted retrieval results."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_type: CrossMeetingCitationType
    record_id: UUID
    meeting_id: UUID
    timestamp: datetime | None = None
    due_at: datetime | None = None
    status: TaskStatus | None = None
    transcript_id: UUID | None = None
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)


class CrossMeetingQuestionResponse(BaseModel):
    """Answer plus server-resolved evidence provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    answer: str = Field(min_length=1, max_length=8000)
    insufficient_evidence: bool
    citations: list[CrossMeetingCitation] = Field(max_length=100)


class CrossMeetingAnswerGenerationRequest(BaseModel):
    """Internal AI request; identity is carried by the signed principal."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)
    evidence: CrossMeetingEvidenceBundle
    task_filter: StructuredTaskFilter = StructuredTaskFilter.ALL

    @field_validator("question")
    @classmethod
    def require_nonblank_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Question must not be blank.")
        return value


__all__ = [
    "CrossMeetingDataQuery",
    "CrossMeetingCitation",
    "CrossMeetingCitationType",
    "CrossMeetingDecisionRecord",
    "CrossMeetingEvidenceBundle",
    "CrossMeetingEvidenceRequest",
    "CrossMeetingAnswerGenerationRequest",
    "CrossMeetingInsightRecord",
    "CrossMeetingRecord",
    "CrossMeetingStructuredData",
    "CrossMeetingQuestionRequest",
    "CrossMeetingQuestionResponse",
    "CrossMeetingTaskRecord",
    "StructuredTaskFilter",
]
