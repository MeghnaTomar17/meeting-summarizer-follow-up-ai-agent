"""
Purpose: Authentication HTTP routes (login, register, refresh, logout).
Future responsibilities: JWT issuance, OAuth callbacks, session invalidation.
Service ownership: gateway-service.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginRequest, TokenResponse
from app.services.authentication_service import AuthenticationService
from shared.database.session import get_db_session
from shared.schemas.user import UserCreate, UserPublic

router = APIRouter(prefix="/auth", tags=["auth"])


async def get_authentication_service(
    session: AsyncSession = Depends(get_db_session),
) -> AuthenticationService:
    """Build the request-scoped authentication application service."""
    return AuthenticationService(session, UserRepository(session), get_settings())


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
