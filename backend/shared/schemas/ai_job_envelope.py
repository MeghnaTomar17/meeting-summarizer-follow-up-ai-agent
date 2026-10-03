"""Primitive, strict transport contract for queued AI-processing jobs."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


QueueOperation = Literal["summary", "tasks", "decisions", "follow_ups", "insights"]


class AIProcessingJobEnvelope(BaseModel):
    """Only the non-sensitive values needed to identify requested work.

    Authentication context, user identity, credentials, lifecycle state, ORM
    data, and AI outputs are intentionally excluded from this wire contract.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    job_id: UUID
    meeting_id: UUID
    transcript_id: UUID
    requested_operations: list[QueueOperation] = Field(min_length=1)

    @field_validator("requested_operations")
    @classmethod
    def deduplicate_operations_preserving_order(
        cls, operations: list[QueueOperation]
    ) -> list[QueueOperation]:
        return list(dict.fromkeys(operations))


__all__ = ["QueueOperation", "AIProcessingJobEnvelope"]
