"""Authenticated user self-service use cases."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.user_repository import UserRepository
from shared.database.models.user import User
from shared.exceptions.common import ConflictError
from shared.schemas.user import UserPublic, UserUpdate


class UserService:
    """Coordinate safe self-service access to the authenticated user's profile."""

    def __init__(self, session: AsyncSession, user_repository: UserRepository) -> None:
        self._session = session
        self._user_repository = user_repository

    async def get_current_user(self, user: User) -> UserPublic:
        """Map the already-authenticated persisted user to the public DTO."""
        return self._to_public(user)

    async def update_current_user(self, user: User, payload: UserUpdate) -> UserPublic:
        """Update the authenticated user's supported profile fields only."""
        email = self._normalize_email(str(payload.email))
        if email == user.email:
            return self._to_public(user)

        existing = await self._user_repository.get_by_email(email)
        if existing is not None and existing.id != user.id:
            raise ConflictError("Email is already registered.")

        user.email = email
        try:
            updated = await self._user_repository.update(user)
            await self._session.commit()
        except IntegrityError as error:
            if self._is_duplicate_email_error(error):
                raise ConflictError("Email is already registered.") from error
            raise
        return self._to_public(updated)

    @staticmethod
    def _normalize_email(email: str) -> str:
        return email.strip().lower()

    @staticmethod
    def _is_duplicate_email_error(error: IntegrityError) -> bool:
        return getattr(error.orig, "constraint_name", None) == "uq_users_email"

    @staticmethod
    def _to_public(user: User) -> UserPublic:
        return UserPublic(id=str(user.id), email=user.email, created_at=user.created_at)
