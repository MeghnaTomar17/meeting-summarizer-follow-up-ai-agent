"""
Purpose: Decision extraction pipeline stage.
Future responsibilities: Invoke DecisionAgent, persist decisions.
Service ownership: ai-service.
"""

from __future__ import annotations

from typing import Any


async def run_decision_extraction(meeting_id: str, transcript: dict[str, Any]) -> list[dict[str, Any]]:
    _ = (meeting_id, transcript)
    raise NotImplementedError
