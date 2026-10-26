"""OpenAI embeddings adapter isolated behind the Search Service provider port."""

from __future__ import annotations

import math
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    RateLimitError,
)
from pydantic import SecretStr

from app.config.settings import SearchSettings, get_settings
from embeddings.contracts import EmbeddingModelIdentity, EmbeddingRequest, EmbeddingResponse
from embeddings.errors import (
    EmbeddingProviderNotConfiguredError,
    EmbeddingProviderUnavailableError,
    EmbeddingRequestRejectedError,
    EmbeddingTimeoutError,
    MalformedEmbeddingResponseError,
    UnexpectedEmbeddingProviderError,
)


class OpenAIEmbeddingProvider:
    """Call the configured OpenAI embeddings endpoint without exposing SDK types."""

    def __init__(
        self,
        *,
        api_key: SecretStr | str | None,
        model: str,
        dimensions: int,
        timeout_seconds: float = 30.0,
        base_url: str | None = None,
        client: AsyncOpenAI | None = None,
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Embedding timeout must be a positive finite number")
        self._api_key = api_key
        self._identity = EmbeddingModelIdentity(
            provider="openai", model=model, dimensions=dimensions
        )
        self._timeout_seconds = timeout_seconds
        self._base_url = base_url
        self._client = client
        self._owns_client = client is None

    @classmethod
    def from_settings(
        cls,
        settings: SearchSettings | None = None,
        *,
        client: AsyncOpenAI | None = None,
    ) -> OpenAIEmbeddingProvider:
        configured = settings or get_settings()
        return cls(
            api_key=configured.embedding_api_key,
            model=configured.embedding_model,
            dimensions=configured.embedding_dimensions,
            timeout_seconds=configured.embedding_timeout_seconds,
            base_url=configured.embedding_base_url,
            client=client,
        )

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        if request.model_identity != self._identity:
            raise EmbeddingRequestRejectedError()
        client = self._get_client()
        try:
            response = await client.embeddings.create(
                model=self._identity.model,
                input=request.texts,
                dimensions=self._identity.dimensions,
            )
        except APITimeoutError:
            raise EmbeddingTimeoutError() from None
        except TimeoutError:
            raise EmbeddingTimeoutError() from None
        except RateLimitError:
            raise EmbeddingProviderUnavailableError() from None
        except APIStatusError as error:
            if error.status_code == 408:
                raise EmbeddingTimeoutError() from None
            if error.status_code == 429 or error.status_code >= 500:
                raise EmbeddingProviderUnavailableError() from None
            if 400 <= error.status_code < 500:
                raise EmbeddingRequestRejectedError() from None
            raise UnexpectedEmbeddingProviderError() from None
        except APIConnectionError:
            raise EmbeddingProviderUnavailableError() from None
        except Exception:
            raise UnexpectedEmbeddingProviderError() from None
        return self._to_response(response, expected_count=len(request.texts))

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.close()
            self._client = None

    def _get_client(self) -> AsyncOpenAI:
        if self._client is not None:
            return self._client
        if self._api_key is None:
            raise EmbeddingProviderNotConfiguredError()
        api_key = (
            self._api_key.get_secret_value()
            if isinstance(self._api_key, SecretStr)
            else self._api_key
        )
        if not api_key.strip():
            raise EmbeddingProviderNotConfiguredError()
        try:
            options: dict[str, Any] = {
                "api_key": api_key,
                "timeout": self._timeout_seconds,
                "max_retries": 0,
            }
            if self._base_url is not None:
                options["base_url"] = self._base_url
            self._client = AsyncOpenAI(**options)
        except Exception:
            raise UnexpectedEmbeddingProviderError() from None
        return self._client

    def _to_response(self, response: Any, *, expected_count: int) -> EmbeddingResponse:
        try:
            data = response.data
            if len(data) != expected_count:
                raise ValueError("Embedding count mismatch")
            indices = [item.index for item in data]
            if sorted(indices) != list(range(expected_count)):
                raise ValueError("Embedding response indices are invalid")
            ordered = sorted(data, key=lambda item: item.index)
            vectors = [item.embedding for item in ordered]
            return EmbeddingResponse(model_identity=self._identity, vectors=vectors)
        except Exception:
            raise MalformedEmbeddingResponseError() from None


__all__ = ["OpenAIEmbeddingProvider"]
