"""Authorized transcript provider for background application execution."""

from __future__ import annotations

from uuid import UUID

from app.services.meeting_service import MeetingService
from shared.exceptions.common import NotFoundError
from shared.schemas.transcript import TranscriptInDB
from shared.security.execution_context import TrustedExecutionContext


class MeetingServiceTranscriptInputProvider:
    """Resolve transcript input through MeetingService's existing ownership path."""

    def __init__(self, meeting_service: MeetingService) -> None:
        self._meeting_service = meeting_service

    async def get_transcript(
        self,
        meeting_id: UUID,
        transcript_id: UUID,
        execution_context: TrustedExecutionContext,
    ) -> TranscriptInDB:
        if (
            not isinstance(execution_context, TrustedExecutionContext)
            or not execution_context.was_issued_by_authenticated_boundary
        ):
            raise PermissionError("Trusted execution context is required.")

        # MeetingService performs the canonical ownership check before lookup.
        transcript = await self._meeting_service.get_transcript(
            str(meeting_id), execution_context.user_id
        )
        if transcript.meeting_id != str(meeting_id) or transcript.id != str(transcript_id):
            # Do not disclose whether a different transcript exists.
            raise NotFoundError("Transcript not found.")
        return transcript
