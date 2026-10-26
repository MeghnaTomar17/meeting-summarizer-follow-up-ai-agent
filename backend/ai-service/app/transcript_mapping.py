"""Map the Meeting Service transcript DTO into provider-neutral agent input.

This module deliberately depends on shared DTOs and normalization only. It
never imports ORM, database, repository, or provider code. Transcripts are
passed to agents in full; Search Service consumes the same normalized source
for deterministic chunking, while token budgeting remains future work.
"""

from __future__ import annotations

from app.contracts import AgentInput, TranscriptContent
from shared.schemas.transcript import TranscriptInDB
from shared.transcripts.normalization import (
    TranscriptNormalizationError,
    normalize_transcript,
)


def build_agent_input(
    transcript: TranscriptInDB,
    *,
    meeting_id: UUID | str,
    meeting_context: dict[str, str] | None = None,
) -> AgentInput:
    """Build deterministic agent input from a retrieved transcript DTO.

    Segment ``index`` is the canonical sequence field, so segments are sorted
    by it and duplicate/negative indices are rejected. Optional speaker and
    timestamp values, transcript text, language, and both identities are kept.
    """
    normalized = normalize_transcript(transcript, meeting_id=meeting_id)
    return AgentInput(
        meeting_id=normalized.meeting_id,
        transcript=TranscriptContent(
            transcript_id=normalized.transcript_id,
            language=normalized.language,
            segments=normalized.segments,
        ),
        meeting_context=meeting_context,
    )


__all__ = ["TranscriptNormalizationError", "build_agent_input"]
