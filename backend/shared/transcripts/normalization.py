"""Canonical validation and ordering for stored transcript DTOs."""

from __future__ import annotations

from uuid import UUID

from pydantic import ValidationError

from shared.schemas.transcript import (
    NormalizedTranscript,
    TranscriptInDB,
    TranscriptSegment,
)


class TranscriptNormalizationError(ValueError):
    """Stored transcript data cannot safely enter AI or Search processing."""


def normalize_transcript(
    transcript: TranscriptInDB,
    *,
    meeting_id: UUID | str,
) -> NormalizedTranscript:
    """Validate transcript identity, segment metadata, and canonical order."""
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

    if not transcript.segments:
        raise TranscriptNormalizationError("Transcript content is required.")

    normalized_segments: list[TranscriptSegment] = []
    seen_indices: set[int] = set()
    for segment in transcript.segments:
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
        return NormalizedTranscript(
            meeting_id=expected_meeting_id,
            transcript_id=transcript_id,
            language=transcript.language,
            segments=normalized_segments,
        )
    except ValidationError:
        raise TranscriptNormalizationError(
            "Transcript content is empty or invalid."
        ) from None


__all__ = ["TranscriptNormalizationError", "normalize_transcript"]
