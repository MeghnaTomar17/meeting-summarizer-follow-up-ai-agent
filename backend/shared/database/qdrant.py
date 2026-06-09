"""
Purpose: Qdrant vector database client factory.
Future responsibilities: Collection management, upsert/search helpers.
Service ownership: Shared module (search-service, worker-service).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qdrant_client import AsyncQdrantClient


_client: "AsyncQdrantClient | None" = None


async def get_qdrant_client() -> "AsyncQdrantClient":
    """Return Qdrant async client — TODO: settings.qdrant_url, api key."""
    global _client
    if _client is None:
        raise NotImplementedError("Qdrant client not configured")
    return _client


async def close_qdrant_client() -> None:
    """Close Qdrant client on shutdown."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None
