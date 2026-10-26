"""Build the configured embedding adapter for Search Service."""

from __future__ import annotations

from openai import AsyncOpenAI

from app.config.settings import SearchSettings, get_settings
from embeddings.contracts import EmbeddingModelIdentity, EmbeddingProvider
from embeddings.errors import EmbeddingProviderNotConfiguredError
from embeddings.openai_provider import OpenAIEmbeddingProvider
from embeddings.service import EmbeddingService


def create_embedding_provider(
    settings: SearchSettings | None = None,
    *,
    client: AsyncOpenAI | None = None,
) -> EmbeddingProvider:
    configured = settings or get_settings()
    if configured.embedding_provider.lower() != "openai":
        raise EmbeddingProviderNotConfiguredError()
    return OpenAIEmbeddingProvider.from_settings(configured, client=client)


def create_embedding_service(
    settings: SearchSettings | None = None,
    *,
    client: AsyncOpenAI | None = None,
) -> EmbeddingService:
    configured = settings or get_settings()
    identity = EmbeddingModelIdentity(
        provider=configured.embedding_provider,
        model=configured.embedding_model,
        dimensions=configured.embedding_dimensions,
    )
    return EmbeddingService(
        create_embedding_provider(configured, client=client), identity
    )


__all__ = ["create_embedding_provider", "create_embedding_service"]
