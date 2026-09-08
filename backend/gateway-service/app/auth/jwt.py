"""
Purpose: JWT encode/decode utilities.
Future responsibilities: Access/refresh tokens, claim validation.
Service ownership: gateway-service.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import jwt


def create_access_token(
    subject: str,
    *,
    secret: str,
    algorithm: str,
    expires_minutes: int,
) -> str:
    """Create a signed, expiring access token for one authenticated user."""
    issued_at = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "type": "access",
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


def decode_access_token(
    token: str,
    *,
    secret: str,
    algorithm: str,
) -> dict[str, object]:
    """Decode and validate a signed access token for internal verification tests."""
    return jwt.decode(token, secret, algorithms=[algorithm])
