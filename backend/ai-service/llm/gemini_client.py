"""
Purpose: Google Gemini API client wrapper.
Future responsibilities: Fallback/alternate provider, multimodal input.
Service ownership: ai-service.
"""

from __future__ import annotations

from typing import Any


class GeminiClient:
    async def complete(self, prompt: str, model: str | None = None) -> str:
        _ = (prompt, model)
        raise NotImplementedError
