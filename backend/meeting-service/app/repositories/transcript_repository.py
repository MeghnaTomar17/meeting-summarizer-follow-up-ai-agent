"""
Purpose: PostgreSQL data access for transcripts.
Future responsibilities: Upsert segments (JSONB), fetch by meeting_id.
Service ownership: meeting-service.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class TranscriptRepository:
    def __init__(self, session: "AsyncSession") -> None:
        self._session = session

    async def upsert(self, meeting_id: str, data: dict[str, Any]) -> dict[str, Any]:
        _ = (meeting_id, data)
        raise NotImplementedError

    async def get_by_meeting_id(self, meeting_id: str) -> dict[str, Any] | None:
        _ = meeting_id
        raise NotImplementedError
