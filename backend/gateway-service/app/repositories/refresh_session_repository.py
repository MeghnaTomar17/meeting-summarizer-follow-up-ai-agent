"""Persistence operations for refresh sessions."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.models.refresh_session import RefreshSession


class RefreshSessionRepository:
    """Database-only refresh-session access; transaction ownership stays in service."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, refresh_session: RefreshSession) -> RefreshSession:
        self._session.add(refresh_session)
        await self._session.flush()
        return refresh_session

    async def get_by_hash_for_update(self, token_hash: str) -> RefreshSession | None:
        statement = (
            select(RefreshSession)
            .where(RefreshSession.token_hash == token_hash)
            .with_for_update()
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def update(self, refresh_session: RefreshSession) -> RefreshSession:
        self._session.add(refresh_session)
        await self._session.flush()
        return refresh_session
