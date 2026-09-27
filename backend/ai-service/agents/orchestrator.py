"""Provider-independent foundation for future AI processing orchestration."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.contracts import (
    ModelRequest,
    ModelResponse,
    ProcessingRequest,
    ProcessingResult,
    ProcessingStatus,
)
from llm.errors import (
    MalformedModelOutputError,
    ModelExecutionError,
    ModelTimeoutError,
    ProviderNotConfiguredError,
    UnexpectedModelProviderError,
)
from llm.provider import ModelProvider

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
        if self._model_provider is None:
            raise ProviderNotConfiguredError()

        provider_request = request.model_copy(
            update={"response_schema": output_model.model_json_schema()}
        )
        try:
            response = await self._model_provider.generate(provider_request)
            if not isinstance(response, ModelResponse):
                response = ModelResponse.model_validate(response)
        except ModelExecutionError:
            raise
        except ValidationError:
            raise MalformedModelOutputError() from None
        except TimeoutError:
            raise ModelTimeoutError() from None
        except Exception:
            raise UnexpectedModelProviderError() from None

        try:
            return output_model.model_validate_json(response.content)
        except ValidationError:
            raise MalformedModelOutputError() from None


__all__ = ["AIProcessingOrchestrator"]
