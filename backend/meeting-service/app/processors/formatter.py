"""
Purpose: Normalize transcript formats (VTT, SRT, plain text, JSON).
Future responsibilities: Unified internal segment schema.
Service ownership: meeting-service.
"""

from __future__ import annotations

from typing import Any


class TranscriptFormatter:
    """Format conversion — TODO: implement parsers."""

    def to_segments(self, raw_content: str, source_format: str) -> list[dict[str, Any]]:
        _ = (raw_content, source_format)
        raise NotImplementedError
