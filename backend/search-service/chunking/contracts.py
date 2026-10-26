"""Typed transcript chunk payload and trusted indexing scope."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TranscriptChunkSegment(BaseModel):
    """Per-segment location/speaker/time metadata without duplicating its text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    index: int = Field(ge=0)
    speaker: str | None = None
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_timestamps(self) -> TranscriptChunkSegment:
        if self.start_ms is not None and self.end_ms is not None and self.end_ms < self.start_ms:
            raise ValueError("Segment end timestamp cannot precede its start timestamp")
        return self


class TranscriptIndexScope(BaseModel):
    """Server-resolved meeting identity and ownership metadata for indexing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    meeting_id: UUID
    transcript_id: UUID
    owner_id: UUID
    organization_id: UUID


class TranscriptChunk(BaseModel):
    """One retrieval text slice and its minimal source/security metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: UUID
    schema_version: int = Field(default=1, ge=1)
    meeting_id: UUID
    transcript_id: UUID
    owner_id: UUID
    organization_id: UUID
    chunk_index: int = Field(ge=0)
    source_segments: list[TranscriptChunkSegment] = Field(min_length=1)
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    language: str | None = None
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_source_metadata(self) -> TranscriptChunk:
        indices = [segment.index for segment in self.source_segments]
        if indices != sorted(set(indices)):
            raise ValueError("Source segments must have unique, nonnegative ordered indices")
        if self.end_ms is not None and self.start_ms is not None and self.end_ms < self.start_ms:
            raise ValueError("Chunk end timestamp cannot precede its start timestamp")
        return self


__all__ = ["TranscriptChunkSegment", "TranscriptIndexScope", "TranscriptChunk"]
