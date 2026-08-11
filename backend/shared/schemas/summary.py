"""
Purpose: Meeting summary schema produced by AI pipeline.
Future responsibilities: Versioned summaries, key topics, executive brief.
Service ownership: Shared (ai-service, gateway-service).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SummaryBase(BaseModel):
    meeting_id: str
    content: str
    key_topics: list[str] = Field(default_factory=list)
    model_provider: str | None = None
    model_name: str | None = None


class SummaryInDB(SummaryBase):
    id: str
    version: int = 1
    created_at: datetime

    # TODO: token_usage, confidence, guardrail_flags
