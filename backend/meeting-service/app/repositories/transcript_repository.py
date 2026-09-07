"""
Purpose: PostgreSQL data access for transcripts.
Future responsibilities: Upsert segments (JSONB), fetch by meeting_id.
Service ownership: meeting-service.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.models.transcript import Transcript


class TranscriptRepository:
    """PostgreSQL data access for persisted transcripts."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_meeting_id(self, meeting_id: UUID) -> Transcript | None:
        statement = select(Transcript).where(Transcript.meeting_id == meeting_id)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def create(self, transcript: Transcript) -> Transcript:
        self._session.add(transcript)
        await self._session.flush()
        return transcript

    async def replace_for_meeting(
        self,
        transcript: Transcript,
        *,
        segments: list[dict[str, Any]],
        language: str | None,
    ) -> Transcript:
        transcript.segments = segments
        transcript.language = language
        await self._session.flush()
        return transcript
