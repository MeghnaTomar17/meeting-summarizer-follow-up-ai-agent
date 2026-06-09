"""
Purpose: Draft follow-up emails after meetings.
Future responsibilities: Tone control, recipient lists, HTML body.
Service ownership: ai-service.
"""

from __future__ import annotations

from typing import Any


class FollowupAgent:
    async def execute(
        self,
        transcript_text: str,
        summary: str,
        tasks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        _ = (transcript_text, summary, tasks)
        raise NotImplementedError
