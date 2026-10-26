"""Search Service application dependency wiring."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends

from app.config.settings import SearchSettings, get_settings
from embeddings.factory import create_embedding_service
from indexing.service import TranscriptIndexingService
from retrieval.semantic_search import SemanticSearch
from vectorstore.qdrant_store import QdrantVectorRepository


async def get_semantic_search_service(
    settings: SearchSettings = Depends(get_settings),
) -> AsyncIterator[SemanticSearch]:
    """Create request-scoped adapters and close their clients after use."""
    service = SemanticSearch(
        create_embedding_service(settings),
        QdrantVectorRepository(settings),
        settings,
    )
    try:
        yield service
    finally:
        await service.aclose()


async def get_transcript_indexing_service(
    settings: SearchSettings = Depends(get_settings),
) -> AsyncIterator[TranscriptIndexingService]:
    """Create request-scoped indexing adapters and close them after use."""
    service = TranscriptIndexingService(
        create_embedding_service(settings),
        QdrantVectorRepository(settings),
        settings,
    )
    try:
        yield service
    finally:
        await service.aclose()


__all__ = ["get_semantic_search_service", "get_transcript_indexing_service"]
