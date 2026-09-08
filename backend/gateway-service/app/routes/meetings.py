"""
Purpose: Meeting API facade — proxies/aggregates meeting-service.
Future responsibilities: List/detail meetings, trigger processing, BFF patterns.
Service ownership: gateway-service (delegates to meeting-service).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status

from app.auth.dependencies import get_current_user
from app.config.settings import GatewaySettings, get_settings
from app.services.meeting_client import MeetingServiceClient
from shared.database.models.user import User
from shared.schemas.meeting import (
    MeetingCreateRequest,
    MeetingPublic,
    MeetingStatusUpdate,
    MeetingUpdate,
)
from shared.schemas.transcript import TranscriptInDB, TranscriptWrite

router = APIRouter(prefix="/meetings", tags=["meetings"])


def get_meeting_client(
    settings: GatewaySettings = Depends(get_settings),
) -> MeetingServiceClient:
    """Build the Gateway's authenticated Meeting Service client."""
    return MeetingServiceClient(settings)


def _request_id(request: Request) -> str | None:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else None


@router.post("", response_model=MeetingPublic, status_code=status.HTTP_201_CREATED)
async def create_meeting(
    payload: MeetingCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    client: MeetingServiceClient = Depends(get_meeting_client),
) -> MeetingPublic:
    return await client.create_meeting(
        payload,
        user_id=current_user.id,
        request_id=_request_id(request),
    )


@router.get("/{meeting_id}", response_model=MeetingPublic)
async def get_meeting(
    meeting_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    client: MeetingServiceClient = Depends(get_meeting_client),
) -> MeetingPublic:
    return await client.get_meeting(
        meeting_id,
        user_id=current_user.id,
        request_id=_request_id(request),
    )


@router.patch("/{meeting_id}", response_model=MeetingPublic)
async def update_meeting(
    meeting_id: str,
    payload: MeetingUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    client: MeetingServiceClient = Depends(get_meeting_client),
) -> MeetingPublic:
    return await client.update_meeting(
        meeting_id,
        payload,
        user_id=current_user.id,
        request_id=_request_id(request),
    )


@router.patch("/{meeting_id}/status", response_model=MeetingPublic)
async def update_meeting_status(
    meeting_id: str,
    payload: MeetingStatusUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    client: MeetingServiceClient = Depends(get_meeting_client),
) -> MeetingPublic:
    return await client.update_meeting_status(
        meeting_id,
        payload.status,
        user_id=current_user.id,
        request_id=_request_id(request),
    )


@router.post(
    "/{meeting_id}/transcript",
    response_model=TranscriptInDB,
    status_code=status.HTTP_201_CREATED,
)
async def create_transcript(
    meeting_id: str,
    payload: TranscriptWrite,
    request: Request,
    current_user: User = Depends(get_current_user),
    client: MeetingServiceClient = Depends(get_meeting_client),
) -> TranscriptInDB:
    return await client.create_transcript(
        meeting_id,
        payload,
        user_id=current_user.id,
        request_id=_request_id(request),
    )


@router.get("/{meeting_id}/transcript", response_model=TranscriptInDB)
async def get_transcript(
    meeting_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    client: MeetingServiceClient = Depends(get_meeting_client),
) -> TranscriptInDB:
    return await client.get_transcript(
        meeting_id,
        user_id=current_user.id,
        request_id=_request_id(request),
    )


@router.put("/{meeting_id}/transcript", response_model=TranscriptInDB)
async def replace_transcript(
    meeting_id: str,
    payload: TranscriptWrite,
    request: Request,
    current_user: User = Depends(get_current_user),
    client: MeetingServiceClient = Depends(get_meeting_client),
) -> TranscriptInDB:
    return await client.replace_transcript(
        meeting_id,
        payload,
        user_id=current_user.id,
        request_id=_request_id(request),
    )
