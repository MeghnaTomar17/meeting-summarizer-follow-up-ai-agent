"""Trusted transcript source and compact indexing result contracts."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from shared.schemas.transcript import TranscriptInDB


class TranscriptIndexSource(BaseModel):
    """Persisted transcript plus authoritative meeting organization metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transcript: TranscriptInDB
    organization_id: UUID


class TranscriptIndexingResult(BaseModel):
    """Safe summary of a completed transcript-index replacement."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    meeting_id: UUID
    transcript_id: UUID
    status: Literal["indexed", "empty"]
    chunk_count: int = Field(ge=0)
