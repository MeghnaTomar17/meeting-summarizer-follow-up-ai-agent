"""Application boundary for transcript processing and domain-ready results.

The service coordinates transcript normalization, AI orchestration, and domain
mapping. It intentionally has no persistence dependency; a caller decides
whether and when to pass successful mapped inputs to domain services.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from agents.decision_agent import DecisionAgentOutput
from agents.followup_agent import FollowUpAgentOutput
from agents.insight_agent import InsightAgentOutput
from agents.orchestrator import AIProcessingOrchestrator
from agents.summary_agent import SummaryAgentOutput
from agents.task_agent import TaskAgentOutput
from app import domain_mapping
from app.contracts import (
    AgentInput,
    ProcessingOperation,
    ProcessingRequest,
    ProcessingStatus,
)
from app.processing_results import (
    AIProcessingResult,
    AgentOutput,
    DecisionDomainInputs,
    FollowupDomainInputs,
    InsightDomainInputs,
    MappedOperationResult,
    MappedOutput,
    OperationResult,
    OperationStatus,
    ProcessingErrorCode,
    ProcessingFailure,
    ProcessingResult,
    TaskDomainInputs,
    failure_for_exception,
)
from app.transcript_mapping import TranscriptNormalizationError, build_agent_input
from shared.schemas.decision import DecisionBase
from shared.schemas.followup import FollowupBase
from shared.schemas.meeting_insight import MeetingInsightBase
from shared.schemas.summary import SummaryBase
from shared.schemas.task import TaskBase
from shared.schemas.transcript import TranscriptInDB


class AgentInputBuilder(Protocol):
    def __call__(
        self, transcript: TranscriptInDB, *, meeting_id: UUID | str
    ) -> AgentInput: ...


class DomainOutputMapper(Protocol):
    def map_summary_output(
        self, output: SummaryAgentOutput, *, meeting_id: UUID | str
    ) -> SummaryBase: ...

    def map_task_output(
        self, output: TaskAgentOutput, *, meeting_id: UUID | str
    ) -> list[TaskBase]: ...

    def map_decision_output(
        self, output: DecisionAgentOutput, *, meeting_id: UUID | str
    ) -> list[DecisionBase]: ...

    def map_followup_output(
        self, output: FollowUpAgentOutput, *, meeting_id: UUID | str
    ) -> list[FollowupBase]: ...

    def map_insight_output(
        self, output: InsightAgentOutput, *, meeting_id: UUID | str
    ) -> list[MeetingInsightBase]: ...


_MAPPER_METHODS = {
    ProcessingOperation.SUMMARY: "map_summary_output",
    ProcessingOperation.TASKS: "map_task_output",
    ProcessingOperation.DECISIONS: "map_decision_output",
    ProcessingOperation.FOLLOW_UPS: "map_followup_output",
    ProcessingOperation.INSIGHTS: "map_insight_output",
}
_MAPPED_ITEM_TYPES = {
    ProcessingOperation.SUMMARY: SummaryBase,
    ProcessingOperation.TASKS: TaskBase,
    ProcessingOperation.DECISIONS: DecisionBase,
    ProcessingOperation.FOLLOW_UPS: FollowupBase,
    ProcessingOperation.INSIGHTS: MeetingInsightBase,
}
_MAPPED_OUTPUT_TYPES = {
    ProcessingOperation.SUMMARY: SummaryBase,
    ProcessingOperation.TASKS: TaskDomainInputs,
    ProcessingOperation.DECISIONS: DecisionDomainInputs,
    ProcessingOperation.FOLLOW_UPS: FollowupDomainInputs,
    ProcessingOperation.INSIGHTS: InsightDomainInputs,
}


class AIProcessingService:
    """Build agent input, invoke the orchestrator, and map successful outputs."""

    def __init__(
        self,
        orchestrator: AIProcessingOrchestrator,
        *,
        input_builder: AgentInputBuilder = build_agent_input,
        output_mapper: DomainOutputMapper = domain_mapping,
    ) -> None:
        self._orchestrator = orchestrator
        self._input_builder = input_builder
        self._output_mapper = output_mapper

    async def process(
        self,
        request: ProcessingRequest,
        transcript: TranscriptInDB,
    ) -> AIProcessingResult:
        """Return ordered, mapped results without persisting domain records."""
        try:
            transcript_id = UUID(transcript.id)
            if transcript_id != request.transcript_id:
                raise TranscriptNormalizationError(
                    "Transcript does not match the requested transcript."
                )
            agent_input = self._input_builder(
                transcript, meeting_id=request.meeting_id
            )
            if (
                not isinstance(agent_input, AgentInput)
                or agent_input.meeting_id != request.meeting_id
                or agent_input.transcript.transcript_id != request.transcript_id
            ):
                raise TranscriptNormalizationError(
                    "Normalized transcript identity does not match the request."
                )
        except Exception:
            return self._failed_result(
                request,
                ProcessingFailure(
                    code=ProcessingErrorCode.INVALID_INPUT,
                    message="Transcript input is invalid for the requested meeting.",
                ),
            )

        try:
            processing_result = await self._orchestrator.process(request, agent_input)
            if not self._result_matches_request(processing_result, request):
                raise ValueError("Orchestrator result did not match its request.")
        except Exception as error:
            return self._failed_result(request, failure_for_exception(error))

        mapped_results: list[MappedOperationResult] = []
        for result in processing_result.results:
            if result.status == OperationStatus.FAILED:
                mapped_results.append(
                    MappedOperationResult(
                        operation=result.operation,
                        status=OperationStatus.FAILED,
                        error=result.error,
                    )
                )
                continue

            try:
                output = self._map_output(
                    result.operation, result.output, request.meeting_id
                )
            except Exception:
                mapped_results.append(
                    MappedOperationResult(
                        operation=result.operation,
                        status=OperationStatus.FAILED,
                        error=ProcessingFailure(
                            code=ProcessingErrorCode.DOMAIN_MAPPING_FAILED,
                            message=(
                                "AI output could not be mapped to the current "
                                "domain contract."
                            ),
                        ),
                    )
                )
            else:
                mapped_results.append(
                    MappedOperationResult(
                        operation=result.operation,
                        status=OperationStatus.COMPLETED,
                        output=output,
                    )
                )

        successes = sum(
            item.status == OperationStatus.COMPLETED for item in mapped_results
        )
        failures = len(mapped_results) - successes
        status = (
            ProcessingStatus.COMPLETED
            if failures == 0
            else ProcessingStatus.FAILED
            if successes == 0
            else ProcessingStatus.PARTIALLY_FAILED
        )
        return AIProcessingResult(
            meeting_id=request.meeting_id,
            transcript_id=request.transcript_id,
            requested_operations=request.requested_operations,
            status=status,
            results=mapped_results,
        )

    @staticmethod
    def _result_matches_request(
        result: ProcessingResult, request: ProcessingRequest
    ) -> bool:
        return (
            isinstance(result, ProcessingResult)
            and result.meeting_id == request.meeting_id
            and result.transcript_id == request.transcript_id
            and result.requested_operations == request.requested_operations
        )

    def _map_output(
        self,
        operation: ProcessingOperation,
        output: AgentOutput | None,
        meeting_id: UUID,
    ) -> MappedOutput:
        if output is None:
            raise ValueError("Successful orchestration result has no output.")
        method = getattr(self._output_mapper, _MAPPER_METHODS[operation])
        mapped = method(output, meeting_id=meeting_id)
        expected = _MAPPED_ITEM_TYPES[operation]
        if expected is SummaryBase:
            if type(mapped) is not SummaryBase:
                raise ValueError("Mapper returned the wrong domain input.")
            return mapped
        if not isinstance(mapped, list) or any(
            type(item) is not expected for item in mapped
        ):
            raise ValueError("Mapper returned the wrong domain inputs.")
        return _MAPPED_OUTPUT_TYPES[operation](items=mapped)

    @staticmethod
    def _failed_result(
        request: ProcessingRequest,
        failure: ProcessingFailure,
    ) -> AIProcessingResult:
        results = [
            MappedOperationResult(
                operation=operation,
                status=OperationStatus.FAILED,
                error=failure,
            )
            for operation in request.requested_operations
        ]
        return AIProcessingResult(
            meeting_id=request.meeting_id,
            transcript_id=request.transcript_id,
            requested_operations=request.requested_operations,
            status=ProcessingStatus.FAILED,
            results=results,
        )


__all__ = ["AIProcessingService", "AgentInputBuilder", "DomainOutputMapper"]
