"""Fail-closed application provider composition."""

from __future__ import annotations

import httpx

from app.config.settings import AISettings, get_settings
from llm.errors import ProviderNotConfiguredError
from llm.model_registry import OLLAMA_PROVIDER, UnsupportedModelConfiguration, resolve_model
from llm.ollama_client import OllamaModelProvider


def create_model_provider(
    settings: AISettings | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> OllamaModelProvider:
    """Build only the selected, exactly registered local Ollama provider.

    There is intentionally no paid-provider fallback. Unsupported provider or
    model configuration fails before a request can be sent.
    """
    configured = settings or get_settings()
    provider = configured.ai_model_provider
    model = configured.ai_model
    if provider != OLLAMA_PROVIDER:
        raise ProviderNotConfiguredError()
    try:
        resolve_model(provider, model)
    except UnsupportedModelConfiguration:
        raise ProviderNotConfiguredError() from None
    return OllamaModelProvider(
        base_url=str(configured.ollama_base_url),
        model=model,
        timeout_seconds=configured.ollama_timeout_seconds,
        client=client,
    )


__all__ = ["create_model_provider"]
