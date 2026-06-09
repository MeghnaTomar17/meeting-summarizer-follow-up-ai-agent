"""
Purpose: Decision records extracted from meeting discourse.
Future responsibilities: Link to transcript evidence, stakeholders.
Service ownership: Shared (ai-service).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DecisionBase(BaseModel):
    meeting_id: str
    statement: str
    context: str | None = None
    participants: list[str] = Field(default_factory=list)


class DecisionInDB(DecisionBase):
    id: str
    created_at: datetime

    # TODO: evidence_segment_indices, confidence
