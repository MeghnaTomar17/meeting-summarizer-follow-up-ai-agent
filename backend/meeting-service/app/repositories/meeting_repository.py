"""
Purpose: PostgreSQL data access for meetings.
Future responsibilities: CRUD via SQLAlchemy, queries by org/user, status updates.
Service ownership: meeting-service.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class MeetingRepository:
    """Repository pattern — TODO: inject AsyncSession via FastAPI Depends."""

    def __init__(self, session: "AsyncSession") -> None:
        self._session = session

    async def create(self, data: dict[str, Any]) -> dict[str, Any]:
        _ = data
        raise NotImplementedError

    async def get_by_id(self, meeting_id: str) -> dict[str, Any] | None:
        _ = meeting_id
        raise NotImplementedError
