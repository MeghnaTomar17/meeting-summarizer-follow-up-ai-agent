"""
Purpose: User profile and administration routes.
Future responsibilities: CRUD profile, org membership, preferences.
Service ownership: gateway-service.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.repositories.user_repository import UserRepository
from app.services.user_service import UserService
from shared.database.models.user import User
from shared.database.session import get_db_session
from shared.schemas.user import UserPublic, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


async def get_user_service(
    session: AsyncSession = Depends(get_db_session),
) -> UserService:
    """Build the request-scoped authenticated user service."""
    return UserService(session, UserRepository(session))


@router.get("/me", response_model=UserPublic)
async def get_my_profile(
    current_user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
) -> UserPublic:
    """Return the current authenticated user's client-safe profile."""
    return await service.get_current_user(current_user)


@router.patch("/me", response_model=UserPublic)
async def update_my_profile(
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
) -> UserPublic:
    """Update the current user's supported profile fields."""
    return await service.update_current_user(current_user, payload)

# TODO: GET /{user_id} (admin)
