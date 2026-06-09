"""
Purpose: Transcript retrieval and ingestion routes.
Future responsibilities: Segment storage, STT callback webhooks.
Service ownership: meeting-service.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/transcripts", tags=["transcripts"])

# TODO: GET /{meeting_id}
# TODO: PUT /{meeting_id} — replace segments after processing
