"""Search Service use case for authenticated owner-scoped retrieval."""

from __future__ import annotations

import logging

from app.config.settings import SearchSettings
from embeddings.contracts import EmbeddingModelIdentity, EmbeddingResponse
from embeddings.service import EmbeddingService
from retrieval.contracts import (
    SearchAuthorizationScope,
    SemanticSearchRequest,
    SemanticSearchResponse,
)
from retrieval.errors import SemanticSearchUnavailableError
from vectorstore.qdrant_store import QdrantVectorRepository

_logger = logging.getLogger(__name__)


class SemanticSearch:
    """Compose the configured embedding model with mandatory owner filtering."""

    def __init__(
        self,
        embedding_service: EmbeddingService,
        repository: QdrantVectorRepository,
        settings: SearchSettings,
    ) -> None:
        self._embedding_service = embedding_service
        self._repository = repository
        self._model_identity = EmbeddingModelIdentity(
            provider=settings.embedding_provider,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
        )

    async def search(
        self,
        request: SemanticSearchRequest,
        *,
        scope: SearchAuthorizationScope,
    ) -> SemanticSearchResponse:
        """Embed one query and return only Qdrant results filtered by owner."""
        if request.meeting_ids == []:
            return SemanticSearchResponse(results=[])
        try:
            embedding_response = await self._embedding_service.embed_texts(
                [request.query]
            )
            validated = EmbeddingResponse.model_validate(
                embedding_response.model_dump(), strict=True
            )
            if (
                validated.model_identity != self._model_identity
                or len(validated.vectors) != 1
            ):
                raise ValueError("Query embedding identity or count mismatch")
        except Exception as error:
            _logger.error(
                "semantic_search_embedding_failed error_type=%s",
                type(error).__name__,
            )
            raise SemanticSearchUnavailableError() from None

        try:
            results = await self._repository.search(
                validated.vectors[0], scope=scope, top_k=request.top_k,
                meeting_ids=request.meeting_ids,
            )
            return SemanticSearchResponse(results=results)
        except Exception as error:
            _logger.error(
                "semantic_search_vector_query_failed error_type=%s",
                type(error).__name__,
            )
            raise SemanticSearchUnavailableError() from None

    async def aclose(self) -> None:
        """Release the owned embedding and vector-store clients."""
        failed = False
        try:
            await self._embedding_service.aclose()
        except Exception:
            failed = True
        try:
            await self._repository.aclose()
        except Exception:
            failed = True
        if failed:
            raise SemanticSearchUnavailableError() from None


__all__ = ["SemanticSearch"]
