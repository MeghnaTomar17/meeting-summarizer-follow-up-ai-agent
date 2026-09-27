"""Shared provider invocation and Pydantic structured-output validation."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.contracts import ModelRequest, ModelResponse
from llm.errors import (
    MalformedModelOutputError,
    ModelExecutionError,
    ModelTimeoutError,
    ProviderNotConfiguredError,
    UnexpectedModelProviderError,
)
from llm.provider import ModelProvider

TOutput = TypeVar("TOutput", bound=BaseModel)


async def generate_structured_output(
    provider: ModelProvider | None,
    request: ModelRequest,
    output_model: type[TOutput],
) -> TOutput:
    """Call the provider and validate its content without exposing raw failures."""
    if provider is None:
        raise ProviderNotConfiguredError()

    provider_request = request.model_copy(
        update={"response_schema": output_model.model_json_schema()}
    )
    try:
        response = await provider.generate(provider_request)
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


__all__ = ["generate_structured_output"]
