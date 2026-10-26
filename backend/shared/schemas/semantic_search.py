"""Public semantic-search request and response DTOs shared by the gateway."""

from __future__ import annotations

import math
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


MAX_SEMANTIC_SEARCH_TOP_K = 50


class SemanticSearchRequest(BaseModel):
    """Natural-language query; caller-supplied authorization scope is forbidden."""

    model_config = ConfigDict(extra="forbid", strict=True)

    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=10, ge=1, le=MAX_SEMANTIC_SEARCH_TOP_K)
    meeting_ids: list[UUID] | None = Field(default=None, max_length=100)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Query must not be blank.")
        return normalized

    @field_validator("meeting_ids", mode="before")
    @classmethod
    def parse_unique_meeting_ids(cls, values: object) -> list[UUID] | None:
        if values is None:
            return None
        if not isinstance(values, list):
            raise ValueError("meeting_ids must be a list of UUIDs.")
        try:
            values = [value if isinstance(value, UUID) else UUID(str(value)) for value in values]
        except (TypeError, ValueError, AttributeError):
            raise ValueError("meeting_ids must contain valid UUIDs.") from None
        if values is not None and len(values) != len(set(values)):
            raise ValueError("meeting_ids must be unique.")
        return values


class SearchSourceSegment(BaseModel):
    """Minimal source location metadata for one indexed transcript segment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    index: int = Field(ge=0)
    speaker: str | None = None
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)


class SemanticSearchResult(BaseModel):
    """Minimal transcript provenance and similarity score; no vector/payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    meeting_id: UUID
    transcript_id: UUID
    chunk_id: UUID
    chunk_index: int = Field(ge=0)
    text: str = Field(min_length=1)
    language: str | None = None
    source_segments: list[SearchSourceSegment] = Field(min_length=1)
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    score: float

    @field_validator("text")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Search result text must not be blank.")
        return value

    @field_validator("score")
    @classmethod
    def require_finite_score(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("Search score must be finite.")
        return value


class SemanticSearchResponse(BaseModel):
    """Results ordered by raw Qdrant score, with higher scores more similar."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    results: list[SemanticSearchResult]


__all__ = [
    "MAX_SEMANTIC_SEARCH_TOP_K",
    "SearchSourceSegment",
    "SemanticSearchRequest",
    "SemanticSearchResponse",
    "SemanticSearchResult",
]
