"""Common typed execution contract for future AI agents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from pydantic import BaseModel

from app.contracts import AgentInput, AgentKind, ModelRequest
from llm.provider import ModelProvider
from llm.structured_output import generate_structured_output

TAgentOutput = TypeVar("TAgentOutput", bound=BaseModel)


class Agent(ABC, Generic[TAgentOutput]):
    """An agent has a stable kind, typed output, injected provider and input."""

    def __init__(self, model_provider: ModelProvider) -> None:
        self._model_provider = model_provider

    @property
    @abstractmethod
    def kind(self) -> AgentKind:
        """Return this agent's controlled identity."""

    @property
    @abstractmethod
    def output_model(self) -> type[TAgentOutput]:
        """Return this agent's Pydantic output contract."""

    @abstractmethod
    def build_model_request(self, agent_input: AgentInput) -> ModelRequest:
        """Build provider-neutral input; prompt/intelligence work stays future scope."""

    async def execute(self, agent_input: AgentInput) -> TAgentOutput:
        """Run a provider request through the shared structured-output boundary."""
        model_request = self.build_model_request(agent_input)
        return await generate_structured_output(
            self._model_provider,
            model_request,
            self.output_model,
        )


__all__ = ["Agent", "TAgentOutput"]
