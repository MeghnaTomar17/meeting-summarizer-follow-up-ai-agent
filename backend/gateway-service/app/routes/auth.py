"""
Purpose: Authentication HTTP routes (login, register, refresh, logout).
Future responsibilities: JWT issuance, OAuth callbacks, session invalidation.
Service ownership: gateway-service.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.config.settings import get_settings
from app.repositories.refresh_session_repository import RefreshSessionRepository
from app.repositories.user_repository import UserRepository
from app.routes.users import get_user_service
from app.schemas.auth import LoginRequest, LogoutResponse, RefreshRequest, TokenResponse
from app.services.authentication_service import AuthenticationService
from app.services.user_service import UserService
from shared.database.models.user import User
from shared.database.session import get_db_session
from shared.schemas.user import UserCreate, UserPublic

router = APIRouter(prefix="/auth", tags=["auth"])


async def get_authentication_service(
    session: AsyncSession = Depends(get_db_session),
) -> AuthenticationService:
    """Build the request-scoped authentication application service."""
    return AuthenticationService(
        session, UserRepository(session), get_settings(), RefreshSessionRepository(session)
    )


@router.post("/signup", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def signup(
    payload: UserCreate,
    service: AuthenticationService = Depends(get_authentication_service),
) -> UserPublic:
    """Register a user through the authentication application service."""
    return await service.signup(payload)


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    service: AuthenticationService = Depends(get_authentication_service),
) -> TokenResponse:
    """Authenticate credentials and issue an access token."""
    return await service.login(payload)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    payload: RefreshRequest,
    service: AuthenticationService = Depends(get_authentication_service),
) -> TokenResponse:
    """Rotate a refresh token and issue a fresh access token pair."""
    return await service.refresh(payload)


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    payload: RefreshRequest,
    service: AuthenticationService = Depends(get_authentication_service),
) -> LogoutResponse:
    """Revoke one refresh session."""
    return await service.logout(payload)


@router.get("/me", response_model=UserPublic)
async def get_authenticated_user(
    current_user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
) -> UserPublic:
    """Return the current external-access-token user's public profile."""
    return await service.get_current_user(current_user)
