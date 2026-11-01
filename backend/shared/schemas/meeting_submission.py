"""Authenticated atomic meeting/transcript/job submission contracts."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from shared.jobs.lifecycle import JobStatus
from shared.schemas.ai_job_envelope import QueueOperation
from shared.schemas.meeting import MeetingCreateRequest
from shared.schemas.transcript import TranscriptWrite


MAX_SUBMISSION_TRANSCRIPT_CHARACTERS = 100_000


class MeetingSubmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meeting: MeetingCreateRequest
    transcript: TranscriptWrite
    requested_operations: list[QueueOperation] = Field(min_length=1, max_length=5)

    @field_validator("requested_operations")
    @classmethod
    def deduplicate_operations(cls, operations: list[QueueOperation]) -> list[QueueOperation]:
        return list(dict.fromkeys(operations))

    @model_validator(mode="after")
    def reject_oversized_transcript(self) -> MeetingSubmissionRequest:
        total_characters = sum(len(segment.text) for segment in self.transcript.segments)
        if total_characters > MAX_SUBMISSION_TRANSCRIPT_CHARACTERS:
            raise ValueError(
                f"Transcript exceeds the {MAX_SUBMISSION_TRANSCRIPT_CHARACTERS}-character submission limit."
            )
        return self


class MeetingSubmissionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    meeting_id: UUID
    transcript_id: UUID
    processing_status: JobStatus


__all__ = [
    "MAX_SUBMISSION_TRANSCRIPT_CHARACTERS",
    "MeetingSubmissionRequest",
    "MeetingSubmissionReceipt",
]
