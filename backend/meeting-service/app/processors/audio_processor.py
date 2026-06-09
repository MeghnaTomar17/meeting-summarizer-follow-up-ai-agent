"""
Purpose: Audio ingestion and speech-to-text orchestration.
Future responsibilities: ffmpeg normalization, STT provider adapter.
Service ownership: meeting-service.
"""

from __future__ import annotations

from pathlib import Path


class AudioProcessor:
    """Process uploaded audio — TODO: integrate STT provider."""

    async def process(self, meeting_id: str, file_path: Path) -> None:
        _ = (meeting_id, file_path)
        raise NotImplementedError
