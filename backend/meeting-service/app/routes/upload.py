"""
Purpose: File upload routes (audio, video, transcript files).
Future responsibilities: Multipart handling, S3 presigned URLs, virus scan hook.
Service ownership: meeting-service.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/upload", tags=["upload"])

# TODO: POST /{meeting_id}/audio
# TODO: POST /{meeting_id}/transcript
# TODO: GET /{meeting_id}/status
