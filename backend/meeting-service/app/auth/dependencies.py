"""Dependencies that verify Gateway-authenticated internal principals."""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose.exceptions import JWTError

from app.config.settings import get_settings
from shared.exceptions.common import UnauthorizedError
from shared.security.internal_principal import verify_internal_principal

security = HTTPBearer(auto_error=False)


async def get_authenticated_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> UUID:
    """Return the user asserted by a valid, Gateway-signed internal principal."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError()

    settings = get_settings()
    try:
        return verify_internal_principal(
            credentials.credentials,
            public_key=settings.internal_principal_public_key,
            algorithm=settings.internal_principal_algorithm,
            issuer=settings.internal_principal_issuer,
            audience=settings.service_name,
        )
    except (JWTError, ValueError):
        raise UnauthorizedError() from None
