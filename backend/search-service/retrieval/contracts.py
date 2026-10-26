"""Provider-neutral request and response contracts for transcript retrieval."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict
from shared.schemas.semantic_search import (
    MAX_SEMANTIC_SEARCH_TOP_K,
    SemanticSearchRequest,
    SemanticSearchResponse,
    SemanticSearchResult,
)



class SearchAuthorizationScope(BaseModel):
    """Internal owner-only scope built from the verified Gateway principal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    owner_id: UUID


__all__ = [
    "SearchAuthorizationScope",
    "MAX_SEMANTIC_SEARCH_TOP_K",
    "SemanticSearchRequest",
    "SemanticSearchResponse",
    "SemanticSearchResult",
]
