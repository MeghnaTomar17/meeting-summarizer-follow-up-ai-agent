"""Authenticated Gateway client for Search Service retrieval."""

from __future__ import annotations

from uuid import UUID

import httpx

from app.config.settings import GatewaySettings
from shared.exceptions.common import ServiceUnavailableError, ValidationError
from shared.schemas.semantic_search import (
    SemanticSearchRequest,
    SemanticSearchResponse,
)
from shared.schemas.transcript_indexing import TranscriptIndexSource, TranscriptIndexingResult
from shared.security.internal_principal import (
    SEARCH_SERVICE_AUDIENCE,
    create_internal_principal,
)


class SearchServiceClient:
    """Proxy Search operations using a narrowly audience-bound internal token."""

    def __init__(self, settings: GatewaySettings) -> None:
        self._settings = settings

    async def search(
        self,
        payload: SemanticSearchRequest,
        *,
        user_id: UUID,
        request_id: str | None,
    ) -> SemanticSearchResponse:
        principal = create_internal_principal(
            user_id,
            private_key=self._settings.internal_principal_private_key.get_secret_value(),
            algorithm=self._settings.internal_principal_algorithm,
            issuer=self._settings.internal_principal_issuer,
            audience=SEARCH_SERVICE_AUDIENCE,
            expires_seconds=self._settings.internal_principal_expire_seconds,
        )
        headers = {"Authorization": f"Bearer {principal}"}
        if request_id:
            headers["X-Request-ID"] = request_id
        body = payload.model_dump(mode="json", exclude_none=True)
        try:
            async with httpx.AsyncClient(
                base_url=self._settings.search_service_url,
                timeout=self._settings.search_service_timeout_seconds,
            ) as client:
                response = await client.post("/search", json=body, headers=headers)
        except httpx.HTTPError:
            raise ServiceUnavailableError("Search service is unavailable.") from None

        if response.status_code == 422:
            raise ValidationError("Search request is invalid.")
        if not 200 <= response.status_code < 300:
            raise ServiceUnavailableError("Search service is unavailable.")
        try:
            return SemanticSearchResponse.model_validate(response.json())
        except Exception:
            raise ServiceUnavailableError("Search service returned an invalid response.") from None

    async def index_transcript(
        self,
        meeting_id: UUID,
        source: TranscriptIndexSource,
        *,
        user_id: UUID,
        request_id: str | None,
    ) -> TranscriptIndexingResult:
        principal = create_internal_principal(
            user_id,
            private_key=self._settings.internal_principal_private_key.get_secret_value(),
            algorithm=self._settings.internal_principal_algorithm,
            issuer=self._settings.internal_principal_issuer,
            audience=SEARCH_SERVICE_AUDIENCE,
            expires_seconds=self._settings.internal_principal_expire_seconds,
        )
        headers = {"Authorization": f"Bearer {principal}"}
        if request_id:
            headers["X-Request-ID"] = request_id
        try:
            async with httpx.AsyncClient(
                base_url=self._settings.search_service_url,
                timeout=self._settings.search_service_index_timeout_seconds,
            ) as client:
                response = await client.post(
                    f"/search/meetings/{meeting_id}/index",
                    json=source.model_dump(mode="json"),
                    headers=headers,
                )
        except httpx.HTTPError:
            raise ServiceUnavailableError("Search service is unavailable.") from None
        if response.status_code == 422:
            raise ValidationError("Transcript indexing request is invalid.")
        if not 200 <= response.status_code < 300:
            raise ServiceUnavailableError("Search service is unavailable.")
        try:
            return TranscriptIndexingResult.model_validate(response.json())
        except Exception:
            raise ServiceUnavailableError("Search service returned an invalid response.") from None


__all__ = ["SearchServiceClient"]
