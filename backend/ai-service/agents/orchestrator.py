"""Sequential application orchestration for independent AI agents."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from agents.base import Agent, TAgentOutput
from agents.decision_agent import DecisionAgent
from agents.followup_agent import FollowUpAgent
from agents.insight_agent import InsightAgent
from agents.summary_agent import SummaryAgent
from agents.task_agent import TaskAgent
from app.contracts import (
    AgentInput,
    ModelRequest,
    ProcessingOperation,
    ProcessingRequest,
    ProcessingStatus,
)
from app.processing_results import (
    OperationResult,
    OperationStatus,
    ProcessingResult,
    failure_for_exception,
)
from llm.errors import ProviderNotConfiguredError
from llm.provider import ModelProvider
from llm.structured_output import generate_structured_output

_AGENT_TYPES = {
    ProcessingOperation.SUMMARY: SummaryAgent,
    ProcessingOperation.TASKS: TaskAgent,
    ProcessingOperation.DECISIONS: DecisionAgent,
    ProcessingOperation.FOLLOW_UPS: FollowUpAgent,
    ProcessingOperation.INSIGHTS: InsightAgent,
}

TOutput = TypeVar("TOutput", bound=BaseModel)


class AIProcessingOrchestrator:
    """Execute each requested agent and retain typed successes and safe failures."""

    def __init__(self, model_provider: ModelProvider | None = None) -> None:
        self._model_provider = model_provider

    async def process(
        self,
        request: ProcessingRequest,
        agent_input: AgentInput,
    ) -> ProcessingResult:
        """Run operations sequentially in request order with partial-failure results."""
        if request.meeting_id != agent_input.meeting_id:
            raise ValueError("Processing request and agent input meeting IDs must match.")
        if request.transcript_id != agent_input.transcript.transcript_id:
            raise ValueError("Processing request and agent input transcript IDs must match.")
        if any(operation not in _AGENT_TYPES for operation in request.requested_operations):
            raise ValueError("Processing request contains an unsupported operation.")

        effective_input = agent_input
        if request.context is not None:
            effective_input = agent_input.model_copy(
                update={"meeting_context": request.context}
            )

        results: list[OperationResult] = []
        for operation in request.requested_operations:
            try:
                if self._model_provider is None:
                    raise ProviderNotConfiguredError()
                agent_type = _AGENT_TYPES.get(operation)
                if agent_type is None:
                    raise ValueError("Unsupported processing operation.")
                agent = agent_type(self._model_provider)
                output = await self.execute_agent(agent, effective_input)
                results.append(
                    OperationResult(
                        operation=operation,
                        status=OperationStatus.COMPLETED,
                        output=output,
                    )
                )
            except Exception as error:
                failure = failure_for_exception(error)
                results.append(
                    OperationResult(
                        operation=operation,
                        status=OperationStatus.FAILED,
                        error=failure,
                    )
                )

        successes = sum(result.status == OperationStatus.COMPLETED for result in results)
        failures = len(results) - successes
        status = (
            ProcessingStatus.COMPLETED
            if failures == 0
            else ProcessingStatus.FAILED
            if successes == 0
            else ProcessingStatus.PARTIALLY_FAILED
        )
        return ProcessingResult(
            meeting_id=request.meeting_id,
            transcript_id=request.transcript_id,
            requested_operations=request.requested_operations,
            status=status,
            results=results,
        )

    async def generate_structured(
        self,
        request: ModelRequest,
        output_model: type[TOutput],
    ) -> TOutput:
        """Generate provider-neutral content and validate it as a Pydantic model."""
        return await generate_structured_output(
            self._model_provider,
            request,
            output_model,
        )

    async def execute_agent(
        self,
        agent: Agent[TAgentOutput],
        agent_input: AgentInput,
    ) -> TAgentOutput:
        """Delegate to the existing typed Agent execution and validation path."""
        return await agent.execute(agent_input)


__all__ = ["AIProcessingOrchestrator"]
