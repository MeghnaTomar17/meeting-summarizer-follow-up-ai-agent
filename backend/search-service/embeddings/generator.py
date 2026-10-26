"""Search Service embedding facade retained at the established module path."""

from __future__ import annotations


from embeddings.contracts import (
    EmbeddingModelIdentity,
    EmbeddingProvider,
    EmbeddingRequest,
    EmbeddingResponse,
)
from embeddings.factory import create_embedding_provider, create_embedding_service
from embeddings.service import EmbeddingService

__all__ = [
    "EmbeddingModelIdentity",
    "EmbeddingProvider",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "EmbeddingService",
    "create_embedding_provider",
    "create_embedding_service",
]
