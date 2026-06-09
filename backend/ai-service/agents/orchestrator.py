"""
Purpose: Coordinate multi-agent AI workflow for a meeting.
Future responsibilities: Pipeline ordering, retries, partial failure handling.
Service ownership: ai-service.
"""

from __future__ import annotations

from typing import Any


class AgentOrchestrator:
    """Run summary → tasks → decisions → followup → insights — TODO."""

    async def run(self, meeting_id: str, transcript: dict[str, Any]) -> dict[str, Any]:
        _ = (meeting_id, transcript)
        raise NotImplementedError
