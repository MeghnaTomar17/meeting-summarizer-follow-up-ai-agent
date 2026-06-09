"""
Purpose: JWT encode/decode utilities.
Future responsibilities: Access/refresh tokens, claim validation.
Service ownership: gateway-service.
"""

from __future__ import annotations

from typing import Any


def create_access_token(subject: str, extra_claims: dict[str, Any] | None = None) -> str:
    """Create JWT access token — TODO: implement with python-jose."""
    _ = (subject, extra_claims)
    raise NotImplementedError


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate JWT — TODO: implement."""
    _ = token
    raise NotImplementedError
