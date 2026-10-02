"""Domain contracts for individual qualitative meeting insights."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, field_validator


class InsightCategory(str, Enum):
    """Controlled insight categories shared by AI and persistence contracts."""

    RISK = "risk"
    BLOCKER = "blocker"
    CONCERN = "concern"
    OPPORTUNITY = "opportunity"
    DEPENDENCY = "dependency"
    UNRESOLVED = "unresolved"
    DISAGREEMENT = "disagreement"
    OBSERVATION = "observation"


class MeetingInsightBase(BaseModel):
    """Trusted application input for one insight belonging to a meeting."""

    model_config = ConfigDict(extra="forbid")

    meeting_id: str
    category: InsightCategory
    title: str
    description: str

    @field_validator("title", "description")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Insight text must not be blank.")
        return value


class MeetingInsightInDB(MeetingInsightBase):
    """Persisted insight fields returned by a future domain service."""

    id: str
    created_at: datetime


__all__ = ["InsightCategory", "MeetingInsightBase", "MeetingInsightInDB"]
