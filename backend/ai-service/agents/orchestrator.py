"""Provider-independent foundation for future AI processing orchestration."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from app.contracts import (
    AgentInput,
    ModelRequest,
    ProcessingRequest,
    ProcessingResult,
    ProcessingStatus,
)
from agents.base import Agent, TAgentOutput
from llm.provider import ModelProvider
from llm.structured_output import generate_structured_output

TOutput = TypeVar("TOutput", bound=BaseModel)


class AIProcessingOrchestrator:
    """Validate the contract and report that execution is not implemented yet.

    The model collaborator is injected; this class constructs neither provider
    clients nor agents. Processing-to-agent mapping remains deferred.
    """

    def __init__(self, model_provider: ModelProvider | None = None) -> None:
        self._model_provider = model_provider

    async def process(self, request: ProcessingRequest) -> ProcessingResult:
        """Preserve the explicit not-implemented result until agents exist."""
        return ProcessingResult(
            meeting_id=request.meeting_id,
            transcript_id=request.transcript_id,
            requested_operations=request.requested_operations,
            status=ProcessingStatus.NOT_IMPLEMENTED,
            sections={},
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
        """Delegate to one typed agent without selecting a workflow or registry."""
        return await agent.execute(agent_input)


__all__ = ["AIProcessingOrchestrator"]
