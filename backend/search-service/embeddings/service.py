"""Provider-neutral application boundary for Search Service embeddings."""

from __future__ import annotations

from collections.abc import Sequence

from chunking.contracts import TranscriptChunk
from embeddings.contracts import (
    EmbeddingModelIdentity,
    EmbeddingProvider,
    EmbeddingRequest,
    EmbeddingResponse,
)
from embeddings.errors import MalformedEmbeddingResponseError


class EmbeddingService:
    """Request embeddings for text or established transcript chunk payloads."""

    def __init__(self, provider: EmbeddingProvider, model_identity: EmbeddingModelIdentity):
        self._provider = provider
        self._model_identity = model_identity

    async def embed_texts(self, texts: Sequence[str]) -> EmbeddingResponse:
        response = await self._provider.embed(
            EmbeddingRequest(model_identity=self._model_identity, texts=list(texts))
        )
        if (
            response.model_identity != self._model_identity
            or len(response.vectors) != len(texts)
        ):
            raise MalformedEmbeddingResponseError()
        return response

    async def embed_chunks(self, chunks: Sequence[TranscriptChunk]) -> EmbeddingResponse:
        return await self.embed_texts([chunk.text for chunk in chunks])

    async def aclose(self) -> None:
        await self._provider.aclose()


__all__ = ["EmbeddingService"]
