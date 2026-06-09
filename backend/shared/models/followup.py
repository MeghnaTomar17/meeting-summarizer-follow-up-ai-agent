"""
Purpose: Follow-up email drafts and delivery state.
Future responsibilities: Template rendering, send scheduling, tracking.
Service ownership: Shared (ai-service, worker-service).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, EmailStr


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


class FollowupInDB(FollowupBase):
    id: str
    status: FollowupStatus = FollowupStatus.DRAFT
    scheduled_at: datetime | None = None
    sent_at: datetime | None = None
    created_at: datetime

    # TODO: provider_message_id, retry_count
