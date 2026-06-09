"""
Purpose: Extract decisions from meeting discourse.
Future responsibilities: Evidence linking, stakeholder tagging.
Service ownership: ai-service.
"""

from __future__ import annotations

from typing import Any


class DecisionAgent:
    async def execute(self, transcript_text: str) -> list[dict[str, Any]]:
        _ = transcript_text
        raise NotImplementedError
