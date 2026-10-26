"""Verify short-lived Gateway-signed principals addressed to Search Service."""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose.exceptions import JWTError

from app.config.settings import SearchSettings, get_settings
from shared.exceptions.common import UnauthorizedError
from shared.security.internal_principal import (
    SEARCH_SERVICE_AUDIENCE,
    verify_internal_principal,
)

security = HTTPBearer(auto_error=False)


async def get_authenticated_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    settings: SearchSettings = Depends(get_settings),
) -> UUID:
    """Return the subject only after signature, issuer, expiry and audience checks."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError()
    try:
        return verify_internal_principal(
            credentials.credentials,
            public_key=settings.internal_principal_public_key,
            algorithm=settings.internal_principal_algorithm,
            issuer=settings.internal_principal_issuer,
            audience=SEARCH_SERVICE_AUDIENCE,
        )
    except (JWTError, ValueError):
        raise UnauthorizedError() from None


__all__ = ["get_authenticated_user_id", "security"]
