"""Provider-neutral text generation interface."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.contracts import ModelRequest, ModelResponse


@runtime_checkable
class ModelProvider(Protocol):
    """Capability required by AI orchestration, independent of provider SDKs.

    Implementations return raw content in a neutral response and raise the
    controlled errors from `llm.errors` for expected provider failures.
    """

    async def generate(self, request: ModelRequest) -> ModelResponse:
        """Generate content for a request without exposing SDK types."""
        ...


__all__ = ["ModelProvider"]
