"""FastAPI dependencies for authenticating the current gateway user."""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose.exceptions import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import decode_access_token
from app.config.settings import get_settings
from app.repositories.user_repository import UserRepository
from shared.database.models.user import User
from shared.database.session import get_db_session
from shared.exceptions.common import UnauthorizedError
from shared.security.execution_context import TrustedExecutionContext

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    session: AsyncSession = Depends(get_db_session),
) -> User:
    """Authenticate an access token and return its persisted user identity."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError()

    settings = get_settings()
    try:
        claims = decode_access_token(
            credentials.credentials,
            secret=settings.jwt_secret.get_secret_value(),
            algorithm=settings.jwt_algorithm,
        )
        if claims.get("type") != "access":
            raise ValueError("Token is not an access token.")
        subject = claims.get("sub")
        if not isinstance(subject, str):
            raise ValueError("Token subject is invalid.")
        user_id = UUID(subject)
    except (JWTError, ValueError):
        raise UnauthorizedError() from None

    user = await UserRepository(session).get_by_id(user_id)
    if user is None:
        raise UnauthorizedError()
    return user


async def get_trusted_execution_context(
    current_user: User = Depends(get_current_user),
) -> TrustedExecutionContext:
    """Carry only the identity established by Gateway authentication downstream."""
    return TrustedExecutionContext._issue_from_authenticated_user_id(current_user.id)
