"""OpenAI implementation of the provider-neutral model interface."""

from __future__ import annotations

import math
import re
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, RateLimitError
from pydantic import SecretStr

from app.config.settings import AISettings, get_settings
from app.contracts import ModelRequest, ModelResponse
from shared.config.base import AppEnv
from llm.errors import (
    MalformedModelOutputError,
    ModelProviderUnavailableError,
    ModelRequestRejectedError,
    ModelTimeoutError,
    ProviderNotConfiguredError,
    UnexpectedModelProviderError,
)
from llm.provider import ModelProvider


class OpenAIModelProvider(ModelProvider):
    """Call OpenAI Chat Completions without leaking SDK types to agents."""

    def __init__(
        self,
        *,
        api_key: SecretStr | str | None,
        model: str | None,
        timeout_seconds: float = 30.0,
        client: AsyncOpenAI | None = None,
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("OpenAI timeout must be a positive finite number.")
        self._api_key = api_key
        self._model = model.strip() if model is not None else None
        self._timeout_seconds = timeout_seconds
        self._client: AsyncOpenAI | None = client
        self._owns_client = client is None

    @classmethod
    def from_settings(
        cls,
        settings: AISettings | None = None,
        *,
        client: AsyncOpenAI | None = None,
    ) -> "OpenAIModelProvider":
        """Create the adapter from the existing AI service settings."""
        configured = settings or get_settings()
        api_key = configured.openai_api_key
        model = configured.openai_model
        has_api_key = api_key is not None and bool(api_key.get_secret_value().strip())
        has_model = model is not None and bool(model.strip())
        if configured.app_env is AppEnv.PRODUCTION and not (has_api_key and has_model):
            raise ProviderNotConfiguredError()
        return cls(
            api_key=api_key,
            model=model,
            timeout_seconds=configured.openai_timeout_seconds,
            client=client,
        )

    async def generate(self, request: ModelRequest) -> ModelResponse:
        """Generate text and return only the provider-neutral response model."""
        if not self._model:
            raise ProviderNotConfiguredError()

        client = self._get_client()
        parameters: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": request.instructions},
                {"role": "user", "content": request.input_text},
            ],
        }
        if request.response_schema is not None:
            parameters["response_format"] = self._response_format(
                request.response_schema
            )

        try:
            response = await client.chat.completions.create(**parameters)
        except APITimeoutError:
            raise ModelTimeoutError() from None
        except TimeoutError:
            raise ModelTimeoutError() from None
        except RateLimitError:
            raise ModelProviderUnavailableError() from None
        except APIStatusError as error:
            if error.status_code == 408:
                raise ModelTimeoutError() from None
            if error.status_code == 429 or error.status_code >= 500:
                raise ModelProviderUnavailableError() from None
            if 400 <= error.status_code < 500:
                raise ModelRequestRejectedError() from None
            raise UnexpectedModelProviderError() from None
        except APIConnectionError:
            raise ModelProviderUnavailableError() from None
        except Exception:
            raise UnexpectedModelProviderError() from None

        return self._to_model_response(response)

    async def aclose(self) -> None:
        """Close the SDK client when this adapter created and owns it."""
        if self._owns_client and self._client is not None:
            await self._client.close()
            self._client = None

    def _get_client(self) -> AsyncOpenAI:
        if self._client is not None:
            return self._client

        if self._api_key is None:
            raise ProviderNotConfiguredError()
        api_key = (
            self._api_key.get_secret_value()
            if isinstance(self._api_key, SecretStr)
            else self._api_key
        )
        if not api_key.strip():
            raise ProviderNotConfiguredError()

        try:
            self._client = AsyncOpenAI(
                api_key=api_key,
                timeout=self._timeout_seconds,
                max_retries=0,
            )
        except Exception:
            raise UnexpectedModelProviderError() from None
        return self._client

    @staticmethod
    def _response_format(schema: dict[str, Any]) -> dict[str, Any]:
        raw_name = schema.get("title")
        name = re.sub(r"[^A-Za-z0-9_-]", "_", raw_name or "model_response")[:64]
        return {
            "type": "json_schema",
            "json_schema": {
                "name": name or "model_response",
                "strict": False,
                "schema": schema,
            },
        }

    @staticmethod
    def _to_model_response(response: Any) -> ModelResponse:
        try:
            choices = response.choices
            if not choices:
                raise ValueError("No completion choices.")
            content = choices[0].message.content
        except Exception:
            raise MalformedModelOutputError() from None

        if not isinstance(content, str) or not content.strip():
            raise MalformedModelOutputError()
        return ModelResponse(content=content)


__all__ = ["OpenAIModelProvider"]
