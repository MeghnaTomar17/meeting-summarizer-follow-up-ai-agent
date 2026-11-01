"""Short-lived service identity assertions for narrowly scoped internal APIs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import jwt
from jose.exceptions import JWTError

SERVICE_PRINCIPAL_TYPE = "service_principal"
OUTBOX_PUBLICATION_ISSUER = "meeting-service"
OUTBOX_PUBLICATION_AUDIENCE = "ai-service:outbox-publication"


def create_service_principal(
    service_name: str,
    *,
    private_key: str,
    issuer: str,
    audience: str,
    expires_seconds: int,
) -> str:
    """Create a short-lived RS256 assertion identifying a service caller."""
    if not service_name or expires_seconds <= 0:
        raise ValueError("Service identity and a positive lifetime are required.")
    issued_at = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": service_name,
            "type": SERVICE_PRINCIPAL_TYPE,
            "iss": issuer,
            "aud": audience,
            "iat": issued_at,
            "exp": issued_at + timedelta(seconds=expires_seconds),
        },
        private_key,
        algorithm="RS256",
    )


def verify_service_principal(
    token: str,
    *,
    public_key: str,
    issuer: str,
    audience: str,
    subject: str,
) -> str:
    """Verify a service identity assertion for one issuer, subject and audience."""
    claims = jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        issuer=issuer,
        audience=audience,
    )
    if claims.get("type") != SERVICE_PRINCIPAL_TYPE or claims.get("sub") != subject:
        raise JWTError("Invalid service principal identity.")
    return subject


__all__ = [
    "SERVICE_PRINCIPAL_TYPE",
    "OUTBOX_PUBLICATION_ISSUER",
    "OUTBOX_PUBLICATION_AUDIENCE",
    "create_service_principal",
    "verify_service_principal",
]
