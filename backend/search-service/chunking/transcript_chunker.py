"""Deterministic, metadata-preserving transcript chunking for Search Service.

Chunk boundaries are between canonical transcript segments. The configured
character size is a target; a single long segment is kept intact rather than
silently truncated or rewritten.
"""

from __future__ import annotations

from uuid import UUID, uuid5

from shared.schemas.transcript import NormalizedTranscript
from chunking.contracts import (
    TranscriptChunk,
    TranscriptChunkSegment,
    TranscriptIndexScope,
)


_CHUNK_POINT_NAMESPACE = UUID("bd2f988b-1f68-5f33-b6e5-8d1984d6dcbc")


def transcript_chunk_id(meeting_id: UUID, transcript_id: UUID, chunk_index: int) -> UUID:
    """Return a stable Qdrant point ID for one transcript/chunk position."""
    if chunk_index < 0:
        raise ValueError("chunk_index must be nonnegative")
    identity = f"v1:{meeting_id}:{transcript_id}:{chunk_index}"
    return uuid5(_CHUNK_POINT_NAMESPACE, identity)


class TranscriptChunker:
    """Group consecutive canonical transcript segments without changing text."""

    def __init__(self, max_characters: int = 2000) -> None:
        if max_characters < 1:
            raise ValueError("max_characters must be positive")
        self._max_characters = max_characters

    def chunk(
        self,
        transcript: NormalizedTranscript,
        *,
        scope: TranscriptIndexScope,
    ) -> list[TranscriptChunk]:
        if (scope.meeting_id, scope.transcript_id) != (
            transcript.meeting_id,
            transcript.transcript_id,
        ):
            raise ValueError("Indexing scope must match the normalized transcript identity")

        groups = []
        current = []
        current_characters = 0
        for segment in transcript.segments:
            added_characters = len(segment.text) + (1 if current else 0)
            if current and current_characters + added_characters > self._max_characters:
                groups.append(current)
                current = []
                current_characters = 0
                added_characters = len(segment.text)
            current.append(segment)
            current_characters += added_characters
        if current:
            groups.append(current)

        chunks: list[TranscriptChunk] = []
        for chunk_index, segments in enumerate(groups):
            starts = [segment.start_ms for segment in segments if segment.start_ms is not None]
            ends = [segment.end_ms for segment in segments if segment.end_ms is not None]
            chunks.append(
                TranscriptChunk(
                    chunk_id=transcript_chunk_id(
                        transcript.meeting_id,
                        transcript.transcript_id,
                        chunk_index,
                    ),
                    meeting_id=scope.meeting_id,
                    transcript_id=scope.transcript_id,
                    owner_id=scope.owner_id,
                    organization_id=scope.organization_id,
                    chunk_index=chunk_index,
                    source_segments=[
                        TranscriptChunkSegment(
                            index=segment.index,
                            speaker=segment.speaker,
                            start_ms=segment.start_ms,
                            end_ms=segment.end_ms,
                        )
                        for segment in segments
                    ],
                    start_ms=min(starts) if starts else None,
                    end_ms=max(ends) if ends else None,
                    language=transcript.language,
                    text="\n".join(segment.text for segment in segments),
                )
            )
        return chunks


__all__ = ["TranscriptChunker", "transcript_chunk_id"]
