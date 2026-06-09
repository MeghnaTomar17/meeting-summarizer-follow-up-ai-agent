"""
Purpose: Meeting API facade — proxies/aggregates meeting-service.
Future responsibilities: List/detail meetings, trigger processing, BFF patterns.
Service ownership: gateway-service (delegates to meeting-service).
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/meetings", tags=["meetings"])

# TODO: GET / — list with pagination
# TODO: POST / — create meeting
# TODO: GET /{meeting_id}
# TODO: PATCH /{meeting_id}
# TODO: DELETE /{meeting_id}
# TODO: POST /{meeting_id}/process — enqueue worker jobs
