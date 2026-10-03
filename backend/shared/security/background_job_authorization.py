"""Purpose-specific signed identity for distributed AI processing jobs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from jose import jwt
from jose.exceptions import JWTError

from shared.schemas.ai_job_envelope import AIProcessingJobEnvelope

_AUTHORIZATION_TYPE = "background_job_authorization"
_ALGORITHM = "RS256"


class JobAuthorizationError(ValueError):
    """A job authorization is absent, invalid, expired, or improperly bound."""


def _validate_private_key(private_key: str) -> None:
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

    try:
        key = load_pem_private_key(private_key.encode(), password=None)
    except (TypeError, ValueError):
        raise JobAuthorizationError("Job authorization signing is unavailable.") from None
    if not isinstance(key, RSAPrivateKey) or key.key_size < 2048:
        raise JobAuthorizationError("Job authorization signing is unavailable.")


def _validate_public_key(public_key: str) -> None:
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

    try:
        key = load_pem_public_key(public_key.encode())
    except (TypeError, ValueError):
        raise JobAuthorizationError("Job authorization verification is unavailable.") from None
    if not isinstance(key, RSAPublicKey) or key.key_size < 2048:
        raise JobAuthorizationError("Job authorization verification is unavailable.")


def _normalize_key(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise JobAuthorizationError("Job authorization key is unavailable.")
    return value.replace("\\n", "\n")


def issue_job_authorization(
    envelope: AIProcessingJobEnvelope,
    user_id: UUID,
    *,
    private_key: str,
    issuer: str = "ai-service",
    audience: str = "mannerai-worker",
    expires_seconds: int = 120,
) -> str:
    """Sign a short-lived authorization bound to one exact primitive envelope."""
    if (
        not isinstance(user_id, UUID)
        or type(expires_seconds) is not int
        or not 1 <= expires_seconds <= 300
        or not isinstance(issuer, str)
        or not issuer.strip()
        or not isinstance(audience, str)
        or not audience.strip()
    ):
        raise JobAuthorizationError("Job authorization could not be issued.")
    key = _normalize_key(private_key)
    _validate_private_key(key)
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "type": _AUTHORIZATION_TYPE,
            "iss": issuer,
            "aud": audience,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=expires_seconds)).timestamp()),
            "jti": str(uuid4()),
            "job_id": str(envelope.job_id),
            "meeting_id": str(envelope.meeting_id),
            "transcript_id": str(envelope.transcript_id),
            "requested_operations": list(envelope.requested_operations),
        },
        key,
        algorithm=_ALGORITHM,
        headers={"typ": "JWT"},
    )


def verify_job_authorization(
    token: str,
    envelope: AIProcessingJobEnvelope,
    *,
    public_key: str,
    issuer: str = "ai-service",
    audience: str = "mannerai-worker",
    max_age_seconds: int = 300,
    clock_skew_seconds: int = 5,
) -> UUID:
    """Verify signature, purpose, lifetime, identity and exact envelope binding."""
    if (
        not isinstance(token, str)
        or not token
        or type(max_age_seconds) is not int
        or not 1 <= max_age_seconds <= 300
        or not isinstance(issuer, str)
        or not issuer.strip()
        or not isinstance(audience, str)
        or not audience.strip()
        or type(clock_skew_seconds) is not int
        or not 0 <= clock_skew_seconds <= 30
    ):
        raise JobAuthorizationError("Job authorization is invalid.")
    key = _normalize_key(public_key)
    _validate_public_key(key)
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=[_ALGORITHM],
            issuer=issuer,
            audience=audience,
            options={
                "require_exp": True,
                "require_iat": True,
                "require_sub": True,
                "leeway": clock_skew_seconds,
            },
        )
        expected_claims = {
            "sub", "type", "iss", "aud", "iat", "exp", "jti", "job_id",
            "meeting_id", "transcript_id", "requested_operations",
        }
        if set(claims) != expected_claims:
            raise JWTError("Unexpected authorization claims.")
        now = int(datetime.now(timezone.utc).timestamp())
        issued_at, expires_at = claims.get("iat"), claims.get("exp")
        if (
            type(issued_at) is not int
            or type(expires_at) is not int
            or issued_at > now + clock_skew_seconds
            or expires_at <= issued_at
            or expires_at - issued_at > max_age_seconds
        ):
            raise JWTError("Invalid authorization lifetime.")
        if claims.get("type") != _AUTHORIZATION_TYPE:
            raise JWTError("Invalid authorization purpose.")
        if (
            claims.get("job_id") != str(envelope.job_id)
            or claims.get("meeting_id") != str(envelope.meeting_id)
            or claims.get("transcript_id") != str(envelope.transcript_id)
            or claims.get("requested_operations") != list(envelope.requested_operations)
        ):
            raise JWTError("Authorization does not bind to this job.")
        subject = claims.get("sub")
        jti = claims.get("jti")
        if not isinstance(subject, str) or not isinstance(jti, str):
            raise JWTError("Invalid authorization subject.")
        UUID(jti)
        return UUID(subject)
    except (JWTError, TypeError, ValueError, KeyError):
        raise JobAuthorizationError("Job authorization is invalid.") from None


__all__ = ["JobAuthorizationError", "issue_job_authorization", "verify_job_authorization"]
