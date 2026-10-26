"""Prepare deterministic transcript chunks and vectors without Qdrant I/O."""

from __future__ import annotations

from uuid import UUID

from pydantic import ValidationError

from chunking.contracts import TranscriptIndexScope
from chunking.transcript_chunker import TranscriptChunker
from embeddings.contracts import EmbeddingModelIdentity
from embeddings.errors import MalformedEmbeddingResponseError
from embeddings.service import EmbeddingService
from indexing.contracts import TranscriptIndexBatch, TranscriptIndexRecord
from shared.schemas.transcript import NormalizedTranscript, TranscriptInDB
from shared.transcripts.normalization import (
    TranscriptNormalizationError,
    normalize_transcript,
)


class TranscriptIndexingInputError(ValueError):
    """The transcript and trusted indexing scope do not form a valid source."""


class DuplicateTranscriptPointIdError(ValueError):
    """Chunking produced duplicate deterministic point IDs."""


class TranscriptIndexingPipeline:
    """Normalize, chunk, embed, and pair one transcript as an all-or-nothing batch."""

    def __init__(
        self,
        *,
        chunker: TranscriptChunker,
        embedding_service: EmbeddingService,
        embedding_model: EmbeddingModelIdentity,
    ) -> None:
        self._chunker = chunker
        self._embedding_service = embedding_service
        self._embedding_model = embedding_model

    async def prepare(
        self,
        transcript: TranscriptInDB | NormalizedTranscript,
        *,
        scope: TranscriptIndexScope,
    ) -> TranscriptIndexBatch:
        """Return a complete batch or raise; never silently drops failed chunks."""
        normalized = self._normalize_and_validate_scope(transcript, scope)
        if normalized is None:
            return TranscriptIndexBatch(
                meeting_id=scope.meeting_id,
                transcript_id=scope.transcript_id,
                records=[],
            )

        chunks = self._chunker.chunk(normalized, scope=scope)
        point_ids = [chunk.chunk_id for chunk in chunks]
        if len(point_ids) != len(set(point_ids)):
            raise DuplicateTranscriptPointIdError(
                "Transcript chunking produced duplicate deterministic point IDs"
            )
        if not chunks:
            return TranscriptIndexBatch(
                meeting_id=scope.meeting_id,
                transcript_id=scope.transcript_id,
                records=[],
            )
        if any(not chunk.text.strip() for chunk in chunks):
            raise TranscriptIndexingInputError(
                "Transcript chunking produced a chunk without embeddable text"
            )

        response = await self._embedding_service.embed_chunks(chunks)
        if (
            response.model_identity != self._embedding_model
            or len(response.vectors) != len(chunks)
        ):
            raise MalformedEmbeddingResponseError()

        try:
            records = [
                TranscriptIndexRecord(
                    point_id=chunk.chunk_id,
                    chunk=chunk,
                    embedding_model=response.model_identity,
                    vector=vector,
                )
                for chunk, vector in zip(chunks, response.vectors, strict=True)
            ]
            return TranscriptIndexBatch(
                meeting_id=scope.meeting_id,
                transcript_id=scope.transcript_id,
                records=records,
            )
        except ValidationError:
            raise MalformedEmbeddingResponseError() from None

    @staticmethod
    def _normalize_and_validate_scope(
        transcript: TranscriptInDB | NormalizedTranscript,
        scope: TranscriptIndexScope,
    ) -> NormalizedTranscript | None:
        if isinstance(transcript, NormalizedTranscript):
            meeting_id = transcript.meeting_id
            transcript_id = transcript.transcript_id
            normalized = transcript
        elif isinstance(transcript, TranscriptInDB):
            try:
                meeting_id = UUID(transcript.meeting_id)
                transcript_id = UUID(transcript.id)
            except (AttributeError, TypeError, ValueError):
                raise TranscriptIndexingInputError(
                    "Transcript identity is invalid for indexing"
                ) from None
            normalized = None
        else:
            raise TranscriptIndexingInputError("Unsupported transcript input")

        if (scope.meeting_id, scope.transcript_id) != (meeting_id, transcript_id):
            raise TranscriptIndexingInputError(
                "Trusted indexing scope must match transcript identity"
            )

        if isinstance(transcript, TranscriptInDB):
            if not transcript.segments or not any(
                segment.text.strip() for segment in transcript.segments
            ):
                return None
            try:
                normalized = normalize_transcript(
                    transcript, meeting_id=scope.meeting_id
                )
            except TranscriptNormalizationError:
                raise TranscriptIndexingInputError(
                    "Transcript failed canonical normalization for indexing"
                ) from None

        return normalized


__all__ = [
    "TranscriptIndexingPipeline",
    "TranscriptIndexingInputError",
    "DuplicateTranscriptPointIdError",
]
