"""
Purpose: Summarization pipeline stage.
Future responsibilities: Invoke SummaryAgent, persist Summary model.
Service ownership: ai-service.
"""

from __future__ import annotations

from typing import Any


async def run_summarization(meeting_id: str, transcript: dict[str, Any]) -> dict[str, Any]:
    _ = (meeting_id, transcript)
    raise NotImplementedError
