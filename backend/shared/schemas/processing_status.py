"""Client-safe view of the latest persisted processing job for a meeting."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from shared.jobs.lifecycle import JobStatus


class MeetingProcessingStatus(BaseModel):
    meeting_id: UUID
    status: JobStatus | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None
