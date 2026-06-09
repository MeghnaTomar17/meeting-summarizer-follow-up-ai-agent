"""
Purpose: Task extraction pipeline stage.
Future responsibilities: Invoke TaskAgent, bulk insert tasks.
Service ownership: ai-service.
"""

from __future__ import annotations

from typing import Any


async def run_task_extraction(meeting_id: str, transcript: dict[str, Any], summary: str) -> list[dict[str, Any]]:
    _ = (meeting_id, transcript, summary)
    raise NotImplementedError
