"""
Purpose: Follow-up email generation pipeline stage.
Future responsibilities: Invoke FollowupAgent, persist draft in PostgreSQL.
Service ownership: ai-service.
"""

from __future__ import annotations

from typing import Any


async def run_followup_generation(meeting_id: str, context: dict[str, Any]) -> dict[str, Any]:
    _ = (meeting_id, context)
    raise NotImplementedError
