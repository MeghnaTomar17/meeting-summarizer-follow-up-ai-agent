"""Strict request and acknowledgment contracts for outbox publication."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from shared.schemas.ai_job_envelope import AIProcessingJobEnvelope


class OutboxPublicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    event_id: UUID
    owner_id: UUID
    job_id: UUID
    event_type: Literal["ai.processing.requested.v1"]
    payload: AIProcessingJobEnvelope

    @model_validator(mode="after")
    def validate_job_identity(self) -> OutboxPublicationRequest:
        if self.payload.job_id != self.job_id:
            raise ValueError("Outbox job identity does not match the envelope.")
        return self


class OutboxPublicationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: UUID
    job_id: UUID


__all__ = ["OutboxPublicationRequest", "OutboxPublicationResponse"]
