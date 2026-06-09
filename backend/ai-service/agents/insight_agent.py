"""
Purpose: Generate meeting insights for analytics dashboards.
Future responsibilities: Sentiment, participation metrics, topic trends.
Service ownership: ai-service.
"""

from __future__ import annotations

from typing import Any


class InsightAgent:
    async def execute(self, transcript_text: str, metadata: dict[str, Any]) -> dict[str, Any]:
        _ = (transcript_text, metadata)
        raise NotImplementedError
