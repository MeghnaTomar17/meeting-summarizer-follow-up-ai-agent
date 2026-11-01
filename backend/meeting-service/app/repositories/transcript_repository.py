"""
Purpose: PostgreSQL data access for transcripts.
Future responsibilities: Upsert segments (JSONB), fetch by meeting_id.
Service ownership: meeting-service.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.models.meeting import Meeting
from shared.database.models.transcript import Transcript


class TranscriptRepository:
    """PostgreSQL data access for persisted transcripts."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_meeting_id(self, meeting_id: UUID) -> Transcript | None:
        statement = (
            select(Transcript)
            .where(Transcript.meeting_id == meeting_id)
            .order_by(Transcript.revision_number.desc(), Transcript.id.desc())
            .limit(1)
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def get_revision(self, meeting_id: UUID, transcript_id: UUID) -> Transcript | None:
        statement = select(Transcript).where(
            Transcript.meeting_id == meeting_id,
            Transcript.id == transcript_id,
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def create(self, transcript: Transcript) -> Transcript:
        self._session.add(transcript)
        await self._session.flush()
        return transcript

    async def create_revision(
        self,
        meeting_id: UUID,
        *,
        segments: list[dict[str, Any]],
        language: str | None,
    ) -> Transcript:
        # Serialize revision-number allocation for this meeting. The unique
        # constraint remains the final guard against concurrent writers.
        meeting_result = await self._session.execute(
            select(Meeting.id).where(Meeting.id == meeting_id).with_for_update()
        )
        if meeting_result.scalar_one_or_none() is None:
            raise LookupError("Meeting not found while creating transcript revision.")
        latest_number = await self._session.scalar(
            select(func.max(Transcript.revision_number)).where(
                Transcript.meeting_id == meeting_id
            )
        )
        transcript = Transcript(
            meeting_id=meeting_id,
            revision_number=(latest_number or 0) + 1,
            segments=segments,
            language=language,
        )
        self._session.add(transcript)
        await self._session.flush()
        return transcript
