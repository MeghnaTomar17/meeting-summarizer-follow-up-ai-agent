"""Typed vector-index records prepared for a future Qdrant repository."""

from __future__ import annotations

import math
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from chunking.contracts import TranscriptChunk
from embeddings.contracts import EmbeddingModelIdentity


class TranscriptIndexRecord(BaseModel):
    """One deterministic transcript chunk paired with its embedding vector."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    point_id: UUID
    chunk: TranscriptChunk
    embedding_model: EmbeddingModelIdentity
    vector: list[float] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_point_and_vector(self) -> TranscriptIndexRecord:
        if self.point_id != self.chunk.chunk_id:
            raise ValueError("Index point ID must match the deterministic chunk ID")
        if len(self.vector) != self.embedding_model.dimensions:
            raise ValueError("Index vector dimensions do not match embedding model")
        if any(not math.isfinite(value) for value in self.vector):
            raise ValueError("Index vectors must contain only finite values")
        return self


class TranscriptIndexBatch(BaseModel):
    """Complete prepared index projection for one transcript; empty is valid."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    meeting_id: UUID
    transcript_id: UUID
    records: list[TranscriptIndexRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_batch(self) -> TranscriptIndexBatch:
        point_ids = [record.point_id for record in self.records]
        if len(point_ids) != len(set(point_ids)):
            raise ValueError("Transcript index batch cannot contain duplicate point IDs")
        chunk_indices = [record.chunk.chunk_index for record in self.records]
        if chunk_indices != list(range(len(self.records))):
            raise ValueError("Transcript index records must be in contiguous chunk order")
        if any(
            record.chunk.meeting_id != self.meeting_id
            or record.chunk.transcript_id != self.transcript_id
            for record in self.records
        ):
            raise ValueError("Transcript index records must match batch identity")
        return self

    @property
    def is_empty(self) -> bool:
        return not self.records

    @property
    def point_ids(self) -> tuple[UUID, ...]:
        return tuple(record.point_id for record in self.records)


__all__ = ["TranscriptIndexRecord", "TranscriptIndexBatch"]
