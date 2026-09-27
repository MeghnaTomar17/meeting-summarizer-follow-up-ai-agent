"""
Purpose: Follow-up email drafts and delivery state.
Future responsibilities: Template rendering, send scheduling, tracking.
Service ownership: Shared (ai-service, worker-service).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, EmailStr, model_validator


class FollowupStatus(str, Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    SENT = "sent"
    FAILED = "failed"


class FollowupBase(BaseModel):
    meeting_id: str
    subject: str
    body_html: str
    recipients: list[EmailStr]


class FollowupCreate(BaseModel):
    """Client fields for creating a follow-up under a meeting URL."""

    model_config = ConfigDict(extra="forbid")

    subject: str
    body_html: str
    recipients: list[EmailStr]


class FollowupInDB(FollowupBase):
    id: str
    status: FollowupStatus = FollowupStatus.DRAFT
    scheduled_at: datetime | None = None
    sent_at: datetime | None = None
    created_at: datetime

    # TODO: provider_message_id, retry_count


class FollowupUpdate(BaseModel):
    """Partial update for the editable draft and persisted status fields."""

    model_config = ConfigDict(extra="forbid")

    subject: str | None = None
    body_html: str | None = None
    recipients: list[EmailStr] | None = None
    status: FollowupStatus | None = None

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> "FollowupUpdate":
        for field_name in ("subject", "body_html", "recipients", "status"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self
