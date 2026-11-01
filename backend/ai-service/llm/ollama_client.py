"""Ollama implementation of the provider-neutral model interface."""

from __future__ import annotations

import math
from typing import Any

import httpx

from app.contracts import ModelRequest, ModelResponse
from llm.errors import (
    MalformedModelOutputError,
    ModelBudgetExceededError,
    ModelBudgetUnverifiedError,
    ModelProviderUnavailableError,
    ModelRequestRejectedError,
    ModelTimeoutError,
    UnexpectedModelProviderError,
)
from llm.model_registry import ModelMetadata, OLLAMA_PROVIDER, resolve_model
from llm.provider import ModelProvider
from llm.token_budget import BudgetAssessment, BudgetStatus, TokenBudgetService


class OllamaModelProvider(ModelProvider):
    """Call Ollama Chat API without leaking HTTP or Ollama response types.

    A default fail-closed budget gate runs before any network request. The gate
    is not replaceable through the provider or application factory API.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Ollama timeout must be a positive finite number.")
        if not base_url.strip():
            raise ValueError("Ollama base URL is required.")
        self._metadata: ModelMetadata = resolve_model(OLLAMA_PROVIDER, model)
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._client = client
        self._owns_client = client is None
        self._budget_service = TokenBudgetService()

    @property
    def provider_id(self) -> str:
        return OLLAMA_PROVIDER

    @property
    def model_id(self) -> str:
        return self._model

    @property
    def model_metadata(self) -> ModelMetadata:
        return self._metadata

    async def generate(self, request: ModelRequest) -> ModelResponse:
        """Require a verified budget, then submit the complete structured chat."""
        assessment = self._budget_service.require_verified_fit(self._metadata, request)
        self._validate_assessment(assessment, request)
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": request.instructions},
                {"role": "user", "content": request.input_text},
            ],
            "options": {
                "num_ctx": assessment.effective_context_limit_tokens,
                "num_predict": assessment.output_reserve_tokens,
            },
            "stream": False,
        }
        if request.response_schema is not None:
            payload["format"] = request.response_schema

        try:
            response = await self._get_client().post(
                f"{self._base_url}/api/chat", json=payload
            )
        except httpx.TimeoutException:
            raise ModelTimeoutError() from None
        except httpx.RequestError:
            raise ModelProviderUnavailableError() from None
        except Exception:
            raise UnexpectedModelProviderError() from None

        if response.status_code == 408:
            raise ModelTimeoutError()
        if response.status_code == 429 or response.status_code >= 500:
            raise ModelProviderUnavailableError()
        if response.status_code >= 400:
            raise ModelRequestRejectedError()

        try:
            body = response.json()
            if body["model"] != self._model or body["done"] is not True:
                raise ValueError("Ollama response identity or completion state is invalid.")
            message = body["message"]
            content = message["content"]
        except (ValueError, TypeError, KeyError):
            raise MalformedModelOutputError() from None
        if not isinstance(content, str) or not content.strip():
            raise MalformedModelOutputError()
        return ModelResponse(content=content)

    def _validate_assessment(
        self, assessment: BudgetAssessment, request: ModelRequest
    ) -> None:
        """Reject malformed or mismatched assessments before contacting Ollama."""
        if not isinstance(assessment, BudgetAssessment):
            raise ModelBudgetUnverifiedError()
        if assessment.status is BudgetStatus.EXCEEDS_BUDGET:
            raise ModelBudgetExceededError()
        if assessment.status is not BudgetStatus.WITHIN_BUDGET:
            raise ModelBudgetUnverifiedError()
        if (
            assessment.provider != self._metadata.provider
            or assessment.model_id != self._metadata.model_id
            or assessment.budget_scope != (request.budget_scope or "unspecified")
            or type(assessment.input_tokens) is not int
            or assessment.input_tokens < 0
            or type(assessment.output_reserve_tokens) is not int
            or assessment.output_reserve_tokens <= 0
            or type(assessment.safety_margin_tokens) is not int
            or assessment.safety_margin_tokens < 0
            or type(assessment.effective_context_limit_tokens) is not int
            or assessment.effective_context_limit_tokens <= 0
            or assessment.effective_context_limit_tokens
            != self._metadata.effective_context_limit_tokens
            or self._metadata.published_context_limit_tokens is None
            or assessment.effective_context_limit_tokens
            > self._metadata.published_context_limit_tokens
            or assessment.input_tokens
            + assessment.output_reserve_tokens
            + assessment.safety_margin_tokens
            > assessment.effective_context_limit_tokens
            or bool(assessment.reasons)
        ):
            raise ModelBudgetUnverifiedError()

    async def aclose(self) -> None:
        """Close only the HTTP client owned by this adapter."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
            )
        return self._client


__all__ = ["OllamaModelProvider"]
