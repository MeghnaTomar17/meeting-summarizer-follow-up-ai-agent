"""Typed aggregate result contracts for AI operation orchestration."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agents.decision_agent import DecisionAgentOutput
from agents.followup_agent import FollowUpAgentOutput
from agents.insight_agent import InsightAgentOutput
from agents.summary_agent import SummaryAgentOutput
from agents.task_agent import TaskAgentOutput
from app.contracts import ProcessingOperation, ProcessingStatus
from llm.errors import (
    MalformedModelOutputError,
    ModelExecutionError,
    ModelProviderUnavailableError,
    ModelRequestRejectedError,
    ModelTimeoutError,
    ProviderNotConfiguredError,
    UnexpectedModelProviderError,
)

AgentOutput = (
    SummaryAgentOutput
    | TaskAgentOutput
    | DecisionAgentOutput
    | FollowUpAgentOutput
    | InsightAgentOutput
)


class OperationStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


class ProcessingErrorCode(StrEnum):
    PROVIDER_NOT_CONFIGURED = "provider_not_configured"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_REJECTED = "provider_rejected"
    MALFORMED_OUTPUT = "malformed_output"
    MODEL_EXECUTION_FAILED = "model_execution_failed"
    UNEXPECTED_FAILURE = "unexpected_failure"


class ProcessingFailure(BaseModel):
    """Sanitized failure details that never expose exception internals."""

    model_config = ConfigDict(extra="forbid", strict=True)

    code: ProcessingErrorCode
    message: str = Field(min_length=1)

    @field_validator("message")
    @classmethod
    def require_nonblank_message(cls, message: str) -> str:
        if not message.strip():
            raise ValueError("Failure message is required.")
        return message


class OperationResult(BaseModel):
    """One operation outcome; successful outputs retain their concrete model."""

    model_config = ConfigDict(extra="forbid", strict=True)

    operation: ProcessingOperation
    status: Literal["completed", "failed"]
    output: AgentOutput | None = None
    error: ProcessingFailure | None = None

    @model_validator(mode="after")
    def validate_outcome_shape(self) -> "OperationResult":
        if self.status == OperationStatus.COMPLETED:
            if self.output is None or self.error is not None:
                raise ValueError("Completed operations require output and no error.")
            expected = {
                ProcessingOperation.SUMMARY: SummaryAgentOutput,
                ProcessingOperation.TASKS: TaskAgentOutput,
                ProcessingOperation.DECISIONS: DecisionAgentOutput,
                ProcessingOperation.FOLLOW_UPS: FollowUpAgentOutput,
                ProcessingOperation.INSIGHTS: InsightAgentOutput,
            }[self.operation]
            if type(self.output) is not expected:
                raise ValueError("Operation output does not match its operation.")
        elif self.output is not None or self.error is None:
            raise ValueError("Failed operations require an error and no output.")
        return self


class ProcessingResult(BaseModel):
    """Typed aggregate AI result, independent of persistence/application mapping."""

    model_config = ConfigDict(extra="forbid", strict=True)

    meeting_id: UUID
    transcript_id: UUID
    requested_operations: list[ProcessingOperation] = Field(min_length=1)
    status: ProcessingStatus
    results: list[OperationResult] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_requested_operation_outcomes(self) -> "ProcessingResult":
        operations = [result.operation for result in self.results]
        if operations != self.requested_operations:
            raise ValueError("Results must match requested operations in order.")
        successes = sum(result.status == OperationStatus.COMPLETED for result in self.results)
        failures = len(self.results) - successes
        expected_status = (
            ProcessingStatus.COMPLETED
            if failures == 0
            else ProcessingStatus.FAILED
            if successes == 0
            else ProcessingStatus.PARTIALLY_FAILED
        )
        if self.status != expected_status:
            raise ValueError("Overall status does not match operation outcomes.")
        return self


def failure_for_exception(error: Exception) -> ProcessingFailure:
    """Map known agent/provider failures to safe public codes and messages."""
    if isinstance(error, ProviderNotConfiguredError):
        code = ProcessingErrorCode.PROVIDER_NOT_CONFIGURED
    elif isinstance(error, ModelProviderUnavailableError):
        code = ProcessingErrorCode.PROVIDER_UNAVAILABLE
    elif isinstance(error, ModelTimeoutError):
        code = ProcessingErrorCode.PROVIDER_TIMEOUT
    elif isinstance(error, ModelRequestRejectedError):
        code = ProcessingErrorCode.PROVIDER_REJECTED
    elif isinstance(error, MalformedModelOutputError):
        code = ProcessingErrorCode.MALFORMED_OUTPUT
    elif isinstance(error, UnexpectedModelProviderError):
        code = ProcessingErrorCode.UNEXPECTED_FAILURE
    elif isinstance(error, ModelExecutionError):
        code = ProcessingErrorCode.MODEL_EXECUTION_FAILED
    else:
        safe_error = UnexpectedModelProviderError()
        return ProcessingFailure(
            code=ProcessingErrorCode.UNEXPECTED_FAILURE,
            message=safe_error.safe_message,
        )
    return ProcessingFailure(code=code, message=error.safe_message)


__all__ = [
    "AgentOutput",
    "OperationResult",
    "OperationStatus",
    "ProcessingErrorCode",
    "ProcessingFailure",
    "ProcessingResult",
    "failure_for_exception",
]
