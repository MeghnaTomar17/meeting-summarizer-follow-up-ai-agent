"""Search service configuration."""

from __future__ import annotations

from pydantic import SecretStr

from shared.config.base import SharedSettings, cached_settings_factory


class SearchSettings(SharedSettings):
    """Search service-specific settings (vector store + embeddings)."""

    service_name: str = "search-service"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr | None = None
    embedding_model: str = "text-embedding-3-small"


get_settings = cached_settings_factory(SearchSettings)

__all__ = ["SearchSettings", "get_settings"]
