"""
Purpose: Meeting analytics pipeline stage.
Future responsibilities: Invoke InsightAgent, write metrics for gateway analytics API.
Service ownership: ai-service.
"""

from __future__ import annotations

from typing import Any


async def run_meeting_analytics(meeting_id: str, transcript: dict[str, Any]) -> dict[str, Any]:
    _ = (meeting_id, transcript)
    raise NotImplementedError
