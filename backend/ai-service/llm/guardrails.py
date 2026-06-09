"""
Purpose: LLM output safety and quality guardrails.
Future responsibilities: PII redaction, policy filters, schema validation.
Service ownership: ai-service.
"""

from __future__ import annotations

from typing import Any


def validate_llm_output(payload: dict[str, Any], schema_name: str) -> dict[str, Any]:
    _ = (payload, schema_name)
    raise NotImplementedError


def redact_pii(text: str) -> str:
    _ = text
    raise NotImplementedError
