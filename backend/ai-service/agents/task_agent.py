"""
Purpose: Extract action items from meeting content.
Future responsibilities: Structured JSON output, assignee inference.
Service ownership: ai-service.
"""

from __future__ import annotations

from typing import Any


class TaskAgent:
    async def execute(self, transcript_text: str, summary: str | None = None) -> list[dict[str, Any]]:
        _ = (transcript_text, summary)
        raise NotImplementedError
