"""
Purpose: Generate embeddings for transcript chunks.
Future responsibilities: Batch processing, provider selection, rate limits.
Service ownership: search-service.
"""

from __future__ import annotations


class EmbeddingGenerator:
    async def generate(self, texts: list[str]) -> list[list[float]]:
        _ = texts
        raise NotImplementedError
