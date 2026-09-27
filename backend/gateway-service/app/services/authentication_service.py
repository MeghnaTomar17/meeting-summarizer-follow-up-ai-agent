"""Signup and login use cases for gateway authentication."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import create_access_token
from app.auth.passwords import hash_password, verify_password
from app.config.settings import GatewaySettings
from app.repositories.user_repository import UserRepository
from app.repositories.refresh_session_repository import RefreshSessionRepository
from app.schemas.auth import LoginRequest, LogoutResponse, RefreshRequest, TokenResponse
from shared.database.models.refresh_session import RefreshSession
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
        refresh_session_repository: RefreshSessionRepository | None = None,
    ) -> None:
        self._session = session
        self._user_repository = user_repository
        self._settings = settings
        self._refresh_sessions = refresh_session_repository or RefreshSessionRepository(session)

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

        response, refresh_session = self._issue_token_pair(user)
        await self._refresh_sessions.create(refresh_session)
        await self._session.commit()
        return response

    async def refresh(self, payload: RefreshRequest) -> TokenResponse:
        """Validate and atomically rotate one opaque refresh session."""
        token_hash = self._hash_refresh_token(payload.refresh_token)
        refresh_session = await self._refresh_sessions.get_by_hash_for_update(token_hash)
        now = datetime.now(timezone.utc)
        if (
            refresh_session is None
            or refresh_session.revoked_at is not None
            or self._as_utc(refresh_session.expires_at) <= now
        ):
            raise UnauthorizedError("Invalid refresh token.")
        user = await self._user_repository.get_by_id(refresh_session.user_id)
        if user is None:
            raise UnauthorizedError("Invalid refresh token.")

        refresh_session.revoked_at = now
        response, replacement = self._issue_token_pair(user)
        await self._refresh_sessions.update(refresh_session)
        await self._refresh_sessions.create(replacement)
        await self._session.commit()
        return response

    async def logout(self, payload: RefreshRequest) -> LogoutResponse:
        """Revoke a refresh session without revealing whether it existed."""
        token_hash = self._hash_refresh_token(payload.refresh_token)
        refresh_session = await self._refresh_sessions.get_by_hash_for_update(token_hash)
        if refresh_session is not None and refresh_session.revoked_at is None:
            refresh_session.revoked_at = datetime.now(timezone.utc)
            await self._refresh_sessions.update(refresh_session)
        await self._session.commit()
        return LogoutResponse()

    def _issue_token_pair(self, user: User) -> tuple[TokenResponse, RefreshSession]:
        raw_token = secrets.token_urlsafe(48)
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=self._settings.refresh_token_expire_seconds
        )
        response = TokenResponse(
            access_token=create_access_token(
                str(user.id),
                secret=self._settings.jwt_secret.get_secret_value(),
                algorithm=self._settings.jwt_algorithm,
                expires_minutes=self._settings.jwt_expire_minutes,
            ),
            refresh_token=raw_token,
        )
        return response, RefreshSession(
            user_id=user.id,
            token_hash=self._hash_refresh_token(raw_token),
            expires_at=expires_at,
        )

    @staticmethod
    def _hash_refresh_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

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
