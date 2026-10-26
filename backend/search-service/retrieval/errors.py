"""Sanitized application failures for semantic retrieval."""

from __future__ import annotations

from shared.exceptions.common import ServiceUnavailableError


class SemanticSearchUnavailableError(ServiceUnavailableError):
    """Provider or vector-store failure without leaking adapter details."""

    def __init__(self) -> None:
        super().__init__("Semantic search is temporarily unavailable.")


__all__ = ["SemanticSearchUnavailableError"]
