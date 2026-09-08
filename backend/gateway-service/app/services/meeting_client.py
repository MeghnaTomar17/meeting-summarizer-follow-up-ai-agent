"""Authenticated Gateway client for the Meeting Service internal API."""

from __future__ import annotations

from uuid import UUID

import httpx

from app.config.settings import GatewaySettings
from shared.exceptions.common import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationError,
)
from shared.schemas.meeting import (
    MeetingCreateRequest,
    MeetingPublic,
    MeetingStatus,
    MeetingUpdate,
)
from shared.schemas.transcript import TranscriptInDB, TranscriptWrite
from shared.security.internal_principal import create_internal_principal


class MeetingServiceClient:
    """Call Meeting Service with a short-lived Gateway-signed principal."""

    def __init__(self, settings: GatewaySettings) -> None:
        self._settings = settings
        self._base_url = settings.meeting_service_url

    async def create_meeting(
        self,
        payload: MeetingCreateRequest,
        *,
        user_id: UUID,
        request_id: str | None,
    ) -> MeetingPublic:
        response = await self._request(
            "POST", "/meetings", payload.model_dump(mode="json"), user_id, request_id
        )
        return MeetingPublic.model_validate(response)

    async def get_meeting(
        self, meeting_id: str, *, user_id: UUID, request_id: str | None
    ) -> MeetingPublic:
        response = await self._request(
            "GET", f"/meetings/{meeting_id}", None, user_id, request_id
        )
        return MeetingPublic.model_validate(response)

    async def update_meeting(
        self,
        meeting_id: str,
        payload: MeetingUpdate,
        *,
        user_id: UUID,
        request_id: str | None,
    ) -> MeetingPublic:
        response = await self._request(
            "PATCH",
            f"/meetings/{meeting_id}",
            payload.model_dump(exclude_unset=True, mode="json"),
            user_id,
            request_id,
        )
        return MeetingPublic.model_validate(response)

    async def update_meeting_status(
        self,
        meeting_id: str,
        status: MeetingStatus,
        *,
        user_id: UUID,
        request_id: str | None,
    ) -> MeetingPublic:
        response = await self._request(
            "PATCH",
            f"/meetings/{meeting_id}/status",
            {"status": status.value},
            user_id,
            request_id,
        )
        return MeetingPublic.model_validate(response)

    async def create_transcript(
        self,
        meeting_id: str,
        payload: TranscriptWrite,
        *,
        user_id: UUID,
        request_id: str | None,
    ) -> TranscriptInDB:
        response = await self._request(
            "POST",
            f"/meetings/{meeting_id}/transcript",
            payload.model_dump(mode="json"),
            user_id,
            request_id,
        )
        return TranscriptInDB.model_validate(response)

    async def get_transcript(
        self, meeting_id: str, *, user_id: UUID, request_id: str | None
    ) -> TranscriptInDB:
        response = await self._request(
            "GET", f"/meetings/{meeting_id}/transcript", None, user_id, request_id
        )
        return TranscriptInDB.model_validate(response)

    async def replace_transcript(
        self,
        meeting_id: str,
        payload: TranscriptWrite,
        *,
        user_id: UUID,
        request_id: str | None,
    ) -> TranscriptInDB:
        response = await self._request(
            "PUT",
            f"/meetings/{meeting_id}/transcript",
            payload.model_dump(mode="json"),
            user_id,
            request_id,
        )
        return TranscriptInDB.model_validate(response)

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None,
        user_id: UUID,
        request_id: str | None,
    ) -> dict[str, object]:
        principal = create_internal_principal(
            user_id,
            private_key=self._settings.internal_principal_private_key.get_secret_value(),
            algorithm=self._settings.internal_principal_algorithm,
            issuer=self._settings.internal_principal_issuer,
            audience="meeting-service",
            expires_seconds=self._settings.internal_principal_expire_seconds,
        )
        headers = {"Authorization": f"Bearer {principal}"}
        if request_id:
            headers["X-Request-ID"] = request_id
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=10.0) as client:
                response = await client.request(method, path, json=payload, headers=headers)
        except httpx.HTTPError as error:
            raise ServiceUnavailableError("Meeting service is unavailable.") from error
        self._raise_for_error(response)
        body = response.json()
        if not isinstance(body, dict):
            raise ServiceUnavailableError("Meeting service returned an invalid response.")
        return body

    @staticmethod
    def _raise_for_error(response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        message = "Request failed."
        try:
            error = response.json().get("error", {})
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                message = error["message"]
        except (ValueError, AttributeError):
            pass
        error_types = {
            403: ForbiddenError,
            404: NotFoundError,
            409: ConflictError,
            422: ValidationError,
        }
        error_type = error_types.get(response.status_code)
        if error_type is not None:
            raise error_type(message)
        raise ServiceUnavailableError("Meeting service is unavailable.")
