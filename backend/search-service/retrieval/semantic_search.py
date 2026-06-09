"""
Purpose: Semantic search orchestration over Qdrant.
Future responsibilities: Hybrid search, reranking, score thresholds.
Service ownership: search-service.
"""

from __future__ import annotations

from typing import Any


class SemanticSearch:
    async def search(
        self,
        query: str,
        organization_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        _ = (query, organization_id, limit)
        raise NotImplementedError
