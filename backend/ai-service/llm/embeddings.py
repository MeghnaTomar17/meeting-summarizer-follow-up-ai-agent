"""
Purpose: Embedding generation abstraction across providers.
Future responsibilities: Batch embed, dimension normalization, caching.
Service ownership: ai-service (also used by search-service via shared pattern).
"""

from __future__ import annotations


class EmbeddingService:
    async def embed_texts(self, texts: list[str], provider: str = "openai") -> list[list[float]]:
        _ = (texts, provider)
        raise NotImplementedError
