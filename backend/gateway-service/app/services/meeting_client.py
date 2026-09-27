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
from shared.schemas.summary import SummaryBase, SummaryInDB
from shared.schemas.task import TaskBase, TaskInDB, TaskUpdate
from shared.schemas.decision import DecisionBase, DecisionInDB
from shared.schemas.followup import FollowupBase, FollowupInDB, FollowupUpdate
from shared.schemas.pagination import PaginatedResponse
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

    async def create_summary(self, meeting_id: str, payload: SummaryBase, *, user_id: UUID, request_id: str | None) -> SummaryInDB:
        return SummaryInDB.model_validate(await self._request("POST", f"/meetings/{meeting_id}/summaries", payload.model_dump(exclude={"meeting_id"}, mode="json"), user_id, request_id))

    async def list_summaries(self, meeting_id: str, *, page: int = 1, page_size: int = 20, user_id: UUID, request_id: str | None) -> PaginatedResponse[SummaryInDB]:
        result = await self._request("GET", f"/meetings/{meeting_id}/summaries?page={page}&page_size={page_size}", None, user_id, request_id)
        return PaginatedResponse[SummaryInDB].model_validate(result)

    async def get_summary(self, meeting_id: str, summary_id: str, *, latest: bool = False, user_id: UUID, request_id: str | None) -> SummaryInDB:
        path = f"/meetings/{meeting_id}/summaries/" + ("latest" if latest else summary_id)
        return SummaryInDB.model_validate(await self._request("GET", path, None, user_id, request_id))

    async def create_task(self, meeting_id: str, payload: TaskBase, *, user_id: UUID, request_id: str | None) -> TaskInDB:
        return TaskInDB.model_validate(await self._request("POST", f"/meetings/{meeting_id}/tasks", payload.model_dump(exclude={"meeting_id"}, mode="json"), user_id, request_id))

    async def list_tasks(self, meeting_id: str, *, task_status: str | None = None, page: int = 1, page_size: int = 20, user_id: UUID, request_id: str | None) -> PaginatedResponse[TaskInDB]:
        path = f"/meetings/{meeting_id}/tasks?page={page}&page_size={page_size}" + (f"&status={task_status}" if task_status else "")
        return PaginatedResponse[TaskInDB].model_validate(await self._request("GET", path, None, user_id, request_id))

    async def get_task(self, meeting_id: str, task_id: str, *, user_id: UUID, request_id: str | None) -> TaskInDB:
        return TaskInDB.model_validate(await self._request("GET", f"/meetings/{meeting_id}/tasks/{task_id}", None, user_id, request_id))

    async def update_task(self, meeting_id: str, task_id: str, payload: TaskUpdate, *, user_id: UUID, request_id: str | None) -> TaskInDB:
        return TaskInDB.model_validate(await self._request("PATCH", f"/meetings/{meeting_id}/tasks/{task_id}", payload.model_dump(exclude_unset=True, mode="json"), user_id, request_id))

    async def create_decision(self, meeting_id: str, payload: DecisionBase, *, user_id: UUID, request_id: str | None) -> DecisionInDB:
        return DecisionInDB.model_validate(await self._request("POST", f"/meetings/{meeting_id}/decisions", payload.model_dump(exclude={"meeting_id"}, mode="json"), user_id, request_id))

    async def list_decisions(self, meeting_id: str, *, page: int = 1, page_size: int = 20, user_id: UUID, request_id: str | None) -> PaginatedResponse[DecisionInDB]:
        path = f"/meetings/{meeting_id}/decisions?page={page}&page_size={page_size}"
        return PaginatedResponse[DecisionInDB].model_validate(await self._request("GET", path, None, user_id, request_id))

    async def get_decision(self, meeting_id: str, decision_id: str, *, user_id: UUID, request_id: str | None) -> DecisionInDB:
        return DecisionInDB.model_validate(await self._request("GET", f"/meetings/{meeting_id}/decisions/{decision_id}", None, user_id, request_id))

    async def create_followup(self, meeting_id: str, payload: FollowupBase, *, user_id: UUID, request_id: str | None) -> FollowupInDB:
        return FollowupInDB.model_validate(await self._request("POST", f"/meetings/{meeting_id}/followups", payload.model_dump(exclude={"meeting_id"}, mode="json"), user_id, request_id))

    async def list_followups(self, meeting_id: str, *, followup_status: str | None = None, page: int = 1, page_size: int = 20, user_id: UUID, request_id: str | None) -> PaginatedResponse[FollowupInDB]:
        path = f"/meetings/{meeting_id}/followups?page={page}&page_size={page_size}" + (f"&status={followup_status}" if followup_status else "")
        return PaginatedResponse[FollowupInDB].model_validate(await self._request("GET", path, None, user_id, request_id))

    async def get_followup(self, meeting_id: str, followup_id: str, *, user_id: UUID, request_id: str | None) -> FollowupInDB:
        return FollowupInDB.model_validate(await self._request("GET", f"/meetings/{meeting_id}/followups/{followup_id}", None, user_id, request_id))

    async def update_followup(self, meeting_id: str, followup_id: str, payload: FollowupUpdate, *, user_id: UUID, request_id: str | None) -> FollowupInDB:
        return FollowupInDB.model_validate(await self._request("PATCH", f"/meetings/{meeting_id}/followups/{followup_id}", payload.model_dump(exclude_unset=True, mode="json"), user_id, request_id))

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None,
        user_id: UUID,
        request_id: str | None,
    ) -> object:
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
        if not isinstance(body, (dict, list)):
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
