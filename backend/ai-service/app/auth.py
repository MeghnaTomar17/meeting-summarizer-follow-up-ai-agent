"""Gateway signed-principal authentication for AI Service internal APIs."""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose.exceptions import JWTError

from app.config.settings import AISettings, get_settings
from shared.exceptions.common import UnauthorizedError
from shared.security.internal_principal import verify_internal_principal
from shared.security.service_principal import (
    OUTBOX_PUBLICATION_AUDIENCE,
    OUTBOX_PUBLICATION_ISSUER,
    verify_service_principal,
)

security = HTTPBearer(auto_error=False)


async def get_authenticated_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    settings: AISettings = Depends(get_settings),
) -> UUID:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError()
    try:
        return verify_internal_principal(
            credentials.credentials,
            public_key=settings.internal_principal_public_key,
            algorithm=settings.internal_principal_algorithm,
            issuer=settings.internal_principal_issuer,
            audience="ai-service",
        )
    except (JWTError, ValueError):
        raise UnauthorizedError() from None


async def get_authenticated_outbox_publisher(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    settings: AISettings = Depends(get_settings),
) -> str:
    """Accept only Meeting Service's dedicated outbox-publication identity."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError()
    public_key = settings.outbox_publication_auth_public_key
    if public_key is None:
        raise UnauthorizedError()
    try:
        return verify_service_principal(
            credentials.credentials,
            public_key=public_key.get_secret_value().replace("\\n", "\n"),
            issuer=OUTBOX_PUBLICATION_ISSUER,
            audience=OUTBOX_PUBLICATION_AUDIENCE,
            subject="meeting-service",
        )
    except (JWTError, ValueError):
        raise UnauthorizedError() from None
