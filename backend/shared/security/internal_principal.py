"""Signed, short-lived authenticated-principal assertions for internal calls."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from jose import jwt
from jose.exceptions import JWTError

_PRINCIPAL_TYPE = "internal_principal"


def create_internal_principal(
    user_id: UUID,
    *,
    private_key: str,
    algorithm: str,
    issuer: str,
    audience: str,
    expires_seconds: int,
) -> str:
    """Create a Gateway-signed assertion for one authenticated user."""
    issued_at = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "type": _PRINCIPAL_TYPE,
            "iss": issuer,
            "aud": audience,
            "iat": issued_at,
            "exp": issued_at + timedelta(seconds=expires_seconds),
        },
        private_key,
        algorithm=algorithm,
    )


def verify_internal_principal(
    token: str,
    *,
    public_key: str,
    algorithm: str,
    issuer: str,
    audience: str,
) -> UUID:
    """Verify a Gateway assertion and return only its authenticated user UUID."""
    claims = jwt.decode(
        token,
        public_key,
        algorithms=[algorithm],
        issuer=issuer,
        audience=audience,
    )
    if claims.get("type") != _PRINCIPAL_TYPE:
        raise JWTError("Invalid internal principal type.")
    subject = claims.get("sub")
    if not isinstance(subject, str):
        raise JWTError("Invalid internal principal subject.")
    try:
        return UUID(subject)
    except ValueError as error:
        raise JWTError("Invalid internal principal subject.") from error
