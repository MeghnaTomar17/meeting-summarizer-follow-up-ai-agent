"""Synchronous Search Service orchestration for persisted transcript indexing."""

from __future__ import annotations

import logging
from uuid import UUID

from app.config.settings import SearchSettings
from chunking.contracts import TranscriptIndexScope
from chunking.transcript_chunker import TranscriptChunker
from embeddings.contracts import EmbeddingModelIdentity
from embeddings.service import EmbeddingService
from indexing.pipeline import TranscriptIndexingPipeline
from retrieval.errors import SemanticSearchUnavailableError
from shared.exceptions.common import ValidationError
from shared.schemas.transcript_indexing import (
    TranscriptIndexSource,
    TranscriptIndexingResult,
)
from vectorstore.qdrant_store import QdrantVectorRepository

_logger = logging.getLogger(__name__)


class TranscriptIndexingService:
    """Prepare a complete embedding batch before replacing its Qdrant projection."""

    def __init__(
        self,
        embedding_service: EmbeddingService,
        repository: QdrantVectorRepository,
        settings: SearchSettings,
        *,
        chunker: TranscriptChunker | None = None,
    ) -> None:
        self._embedding_service = embedding_service
        self._repository = repository
        self._pipeline = TranscriptIndexingPipeline(
            chunker=chunker or TranscriptChunker(settings.transcript_chunk_max_characters),
            embedding_service=embedding_service,
            embedding_model=EmbeddingModelIdentity(
                provider=settings.embedding_provider,
                model=settings.embedding_model,
                dimensions=settings.embedding_dimensions,
            ),
        )

    async def index(
        self,
        source: TranscriptIndexSource,
        *,
        meeting_id: UUID,
        owner_id: UUID,
    ) -> TranscriptIndexingResult:
        """Validate source identity, prepare all vectors, then replace the transcript."""
        try:
            transcript_meeting_id = UUID(source.transcript.meeting_id)
            transcript_id = UUID(source.transcript.id)
            if transcript_meeting_id != meeting_id:
                raise ValidationError("Transcript does not match the requested meeting.")
            scope = TranscriptIndexScope(
                meeting_id=meeting_id,
                transcript_id=transcript_id,
                owner_id=owner_id,
                organization_id=source.organization_id,
            )
        except (ValueError, TypeError):
            raise ValidationError("Transcript source identity is invalid.") from None

        try:
            batch = await self._pipeline.prepare(source.transcript, scope=scope)
            await self._repository.initialize_collection()
            await self._repository.upsert_transcript_batch(batch)
        except Exception as error:
            _logger.error("transcript_indexing_failed error_type=%s", type(error).__name__)
            raise SemanticSearchUnavailableError() from None

        return TranscriptIndexingResult(
            meeting_id=meeting_id,
            transcript_id=transcript_id,
            status="empty" if batch.is_empty else "indexed",
            chunk_count=len(batch.records),
        )

    async def aclose(self) -> None:
        """Release request-scoped provider and Qdrant clients."""
        failures = []
        for adapter in (self._embedding_service, self._repository):
            try:
                await adapter.aclose()
            except Exception as error:
                failures.append(type(error).__name__)
        if failures:
            _logger.error("transcript_indexing_close_failed error_types=%s", failures)
            raise SemanticSearchUnavailableError() from None


__all__ = ["TranscriptIndexingService"]
