"""
Purpose: Meeting aggregate schema.
Future responsibilities: CRUD, lifecycle status, participant links.
Service ownership: Shared (meeting-service, gateway-service).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class MeetingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class MeetingBase(BaseModel):
    title: str
    description: str | None = None
    scheduled_at: datetime | None = None
    participants: list[str] = Field(default_factory=list)


class MeetingCreate(MeetingBase):
    organization_id: str
    created_by: str


class MeetingUpdate(BaseModel):
    """Partial update payload for mutable meeting details."""

    title: str = Field(default_factory=str)
    description: str | None = None
    scheduled_at: datetime | None = None
    participants: list[str] = Field(default_factory=list)


class MeetingInDB(MeetingBase):
    id: str
    organization_id: str
    created_by: str
    status: MeetingStatus = MeetingStatus.PENDING
    created_at: datetime
    updated_at: datetime

    # TODO: recording_url, duration_seconds, source (upload|calendar|zoom)


class MeetingPublic(MeetingBase):
    """Client-safe meeting representation — excludes internal ownership fields."""

    id: str
    status: MeetingStatus = MeetingStatus.PENDING
    created_at: datetime
    updated_at: datetime
