"""
Purpose: Split transcripts into semantic chunks for embedding and RAG.
Future responsibilities: Token-aware chunking, overlap, metadata.
Service ownership: search-service (Search/RAG processing layer).
"""

from __future__ import annotations

from typing import Any


class TranscriptChunker:
    """Chunk transcript segments — TODO: implement strategy."""

    def chunk(self, segments: list[dict[str, Any]], max_tokens: int = 512) -> list[dict[str, Any]]:
        _ = (segments, max_tokens)
        raise NotImplementedError
