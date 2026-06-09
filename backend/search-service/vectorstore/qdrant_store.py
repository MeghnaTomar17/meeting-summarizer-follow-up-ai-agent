"""
Purpose: Qdrant vector store operations.
Future responsibilities: Upsert, delete, filtered search, collection bootstrap.
Service ownership: search-service.
"""

from __future__ import annotations

from typing import Any


class QdrantVectorStore:
    async def upsert_chunks(self, meeting_id: str, chunks: list[dict[str, Any]], vectors: list[list[float]]) -> None:
        _ = (meeting_id, chunks, vectors)
        raise NotImplementedError

    async def search_vectors(
        self,
        vector: list[float],
        organization_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        _ = (vector, organization_id, limit)
        raise NotImplementedError
