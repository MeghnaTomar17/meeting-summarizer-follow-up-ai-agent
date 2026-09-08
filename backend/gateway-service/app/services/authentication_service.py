"""Signup and login use cases for gateway authentication."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import create_access_token
from app.auth.passwords import hash_password, verify_password
from app.config.settings import GatewaySettings
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginRequest, TokenResponse
from shared.database.models.user import User
from shared.exceptions.common import ConflictError, UnauthorizedError
from shared.schemas.user import UserCreate, UserPublic


class AuthenticationService:
    """Application use cases for unauthenticated signup and login."""

    def __init__(
        self,
        session: AsyncSession,
        user_repository: UserRepository,
        settings: GatewaySettings,
    ) -> None:
        self._session = session
        self._user_repository = user_repository
        self._settings = settings

    async def signup(self, payload: UserCreate) -> UserPublic:
        """Create a user with a canonical email and persisted password hash."""
        email = self.normalize_email(str(payload.email))
        existing = await self._user_repository.get_by_email(email)
        if existing is not None:
            raise ConflictError("Email is already registered.")

        user = User(email=email, password_hash=hash_password(payload.password))
        try:
            created = await self._user_repository.create(user)
            await self._session.commit()
        except IntegrityError as error:
            if self._is_duplicate_email_error(error):
                raise ConflictError("Email is already registered.") from error
            raise
        return self._to_public(created)

    async def login(self, payload: LoginRequest) -> TokenResponse:
        """Verify credentials and issue a signed access token on success."""
        email = self.normalize_email(str(payload.email))
        user = await self._user_repository.get_by_email(email)
        if user is None or not verify_password(payload.password, user.password_hash):
            raise UnauthorizedError("Invalid email or password.")

        return TokenResponse(
            access_token=create_access_token(
                str(user.id),
                secret=self._settings.jwt_secret.get_secret_value(),
                algorithm=self._settings.jwt_algorithm,
                expires_minutes=self._settings.jwt_expire_minutes,
            )
        )

    @staticmethod
    def normalize_email(email: str) -> str:
        """Canonicalize login identity consistently at the authentication boundary."""
        return email.strip().lower()

    @staticmethod
    def _is_duplicate_email_error(error: IntegrityError) -> bool:
        return getattr(error.orig, "constraint_name", None) == "uq_users_email"

    @staticmethod
    def _to_public(user: User) -> UserPublic:
        return UserPublic(
            id=str(user.id),
            email=user.email,
            created_at=user.created_at,
        )
