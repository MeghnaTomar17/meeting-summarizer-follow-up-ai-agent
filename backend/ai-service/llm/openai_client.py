"""
Purpose: OpenAI API client wrapper.
Future responsibilities: Chat completions, retries, token accounting.
Service ownership: ai-service.
"""

from __future__ import annotations

from typing import Any


class OpenAIClient:
    """Async OpenAI client — TODO: inject api_key from settings."""

    async def complete(self, messages: list[dict[str, str]], model: str | None = None) -> str:
        _ = (messages, model)
        raise NotImplementedError

    async def embed(self, texts: list[str]) -> list[list[float]]:
        _ = texts
        raise NotImplementedError
