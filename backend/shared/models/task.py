"""
Purpose: Action item / task extracted from meetings.
Future responsibilities: Assignee, due date, status workflow.
Service ownership: Shared (ai-service, gateway-service).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


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


class TaskInDB(TaskBase):
    id: str
    status: TaskStatus = TaskStatus.OPEN
    created_at: datetime
    updated_at: datetime

    # TODO: source_segment_index, confidence
