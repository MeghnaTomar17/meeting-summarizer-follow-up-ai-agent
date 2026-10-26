"""
Purpose: Transcript segment schemas.
Future responsibilities: Store transcript with speaker diarization metadata.
Service ownership: Shared (meeting-service, search-service).
"""

from __future__ import annotations

from datetime import datetime

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TranscriptSegment(BaseModel):
    index: int
    speaker: str | None = None
    text: str
    start_ms: int | None = None
    end_ms: int | None = None


class TranscriptBase(BaseModel):
    meeting_id: str
    segments: list[TranscriptSegment] = Field(default_factory=list)
    language: str = "en"


class TranscriptWrite(BaseModel):
    """Transcript content supplied to nested meeting transcript routes."""

    model_config = ConfigDict(extra="forbid")

    segments: list[TranscriptSegment] = Field(default_factory=list)
    language: str = "en"


class TranscriptInDB(TranscriptBase):
    id: str
    created_at: datetime
    updated_at: datetime

    # TODO: raw_text, source (stt|upload)
    # TODO: chunk_ids — populated after search-service semantic chunking indexes vectors


class NormalizedTranscript(BaseModel):
    """Canonical, ordered transcript source shared by AI and Search boundaries."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    meeting_id: UUID
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

    @model_validator(mode="after")
    def require_canonical_segments(self) -> NormalizedTranscript:
        indices = [segment.index for segment in self.segments]
        if any(index < 0 for index in indices) or indices != sorted(set(indices)):
            raise ValueError("Normalized transcript segments must have unique, nonnegative ordered indices")
        for segment in self.segments:
            if (
                (segment.start_ms is not None and segment.start_ms < 0)
                or (segment.end_ms is not None and segment.end_ms < 0)
                or (
                    segment.start_ms is not None
                    and segment.end_ms is not None
                    and segment.end_ms < segment.start_ms
                )
            ):
                raise ValueError("Transcript segment timestamps are invalid.")
        return self
