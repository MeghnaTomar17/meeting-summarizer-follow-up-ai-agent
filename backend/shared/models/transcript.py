"""
Purpose: Transcript segment models.
Future responsibilities: Store chunked transcript with speaker diarization metadata.
Service ownership: Shared (meeting-service, search-service).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


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


class TranscriptInDB(TranscriptBase):
    id: str
    created_at: datetime
    updated_at: datetime

    # TODO: raw_text, source (stt|upload), chunk_ids for vector index
