"""
Purpose: Generate meeting summaries via LLM.
Future responsibilities: Prompt assembly, model routing, output validation.
Service ownership: ai-service.
"""

from __future__ import annotations

from typing import Any


class SummaryAgent:
    async def execute(self, transcript_text: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        _ = (transcript_text, metadata)
        raise NotImplementedError
