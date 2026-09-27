"""
Purpose: Action item / task schema extracted from meetings.
Future responsibilities: Assignee, due date, status workflow.
Service ownership: Shared (ai-service, gateway-service).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, model_validator


class TaskStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskBase(BaseModel):
    meeting_id: str
    title: str
    description: str | None = None
    assignee_id: str | None = None
    due_at: datetime | None = None


class TaskCreate(BaseModel):
    """Client fields for creating a task under a meeting URL."""

    model_config = ConfigDict(extra="forbid")

    title: str
    description: str | None = None
    assignee_id: str | None = None
    due_at: datetime | None = None


class TaskInDB(TaskBase):
    id: str
    status: TaskStatus = TaskStatus.OPEN
    created_at: datetime
    updated_at: datetime

    # TODO: source_segment_index, confidence


class TaskUpdate(BaseModel):
    """Partial task update; meeting association is immutable."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    description: str | None = None
    assignee_id: str | None = None
    due_at: datetime | None = None
    status: TaskStatus | None = None

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> "TaskUpdate":
        for field_name in ("title", "status"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self
