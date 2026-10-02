"""Map the Meeting Service transcript DTO into provider-neutral agent input.

This module deliberately depends on the shared DTO only. It never imports ORM,
database, repository, or provider code. Transcripts are passed to agents in full;
token budgeting and chunking belong to a later processing/search boundary.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import ValidationError

from app.contracts import AgentInput, TranscriptContent
from shared.schemas.transcript import TranscriptInDB, TranscriptSegment


class TranscriptNormalizationError(ValueError):
    """Raised when stored transcript data cannot safely become agent input."""


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
    try:
        expected_meeting_id = UUID(str(meeting_id))
        transcript_meeting_id = UUID(transcript.meeting_id)
        transcript_id = UUID(transcript.id)
    except (AttributeError, TypeError, ValueError):
        raise TranscriptNormalizationError(
            "Transcript and meeting identifiers must be valid UUIDs."
        ) from None

    if expected_meeting_id != transcript_meeting_id:
        raise TranscriptNormalizationError(
            "Transcript does not belong to the requested meeting."
        )

    source_segments = transcript.segments
    if not source_segments:
        raise TranscriptNormalizationError("Transcript content is required.")

    normalized_segments: list[TranscriptSegment] = []
    seen_indices: set[int] = set()
    for segment in source_segments:
        if not isinstance(segment, TranscriptSegment):
            try:
                segment = TranscriptSegment.model_validate(segment)
            except ValidationError:
                raise TranscriptNormalizationError(
                    "Transcript contains an invalid segment."
                ) from None

        if segment.index < 0 or segment.index in seen_indices:
            raise TranscriptNormalizationError(
                "Transcript segment indices must be unique and nonnegative."
            )
        seen_indices.add(segment.index)

        if (
            (segment.start_ms is not None and segment.start_ms < 0)
            or (segment.end_ms is not None and segment.end_ms < 0)
            or (
                segment.start_ms is not None
                and segment.end_ms is not None
                and segment.end_ms < segment.start_ms
            )
        ):
            raise TranscriptNormalizationError(
                "Transcript segment timestamps are invalid."
            )
        normalized_segments.append(segment)

    normalized_segments.sort(key=lambda segment: segment.index)
    try:
        content = TranscriptContent(
            transcript_id=transcript_id,
            language=transcript.language,
            segments=normalized_segments,
        )
        return AgentInput(
            meeting_id=expected_meeting_id,
            transcript=content,
            meeting_context=meeting_context,
        )
    except ValidationError:
        raise TranscriptNormalizationError(
            "Transcript content is empty or invalid."
        ) from None


__all__ = ["TranscriptNormalizationError", "build_agent_input"]
