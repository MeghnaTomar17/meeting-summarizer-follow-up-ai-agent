"""Authenticated Gateway client for AI Service answer generation."""

from __future__ import annotations

from uuid import UUID

import httpx

from app.config.settings import GatewaySettings
from shared.exceptions.common import ServiceUnavailableError
from shared.schemas.cross_meeting import (
    CrossMeetingAnswerGenerationRequest,
    CrossMeetingQuestionResponse,
)
from shared.security.internal_principal import create_internal_principal


class AIServiceClient:
    def __init__(self, settings: GatewaySettings) -> None:
        self._settings = settings

    async def answer(
        self,
        payload: CrossMeetingAnswerGenerationRequest,
        *,
        user_id: UUID,
        request_id: str | None,
    ) -> CrossMeetingQuestionResponse:
        principal = create_internal_principal(
            user_id,
            private_key=self._settings.internal_principal_private_key.get_secret_value(),
            algorithm=self._settings.internal_principal_algorithm,
            issuer=self._settings.internal_principal_issuer,
            audience="ai-service",
            expires_seconds=self._settings.internal_principal_expire_seconds,
        )
        headers = {"Authorization": f"Bearer {principal}"}
        if request_id:
            headers["X-Request-ID"] = request_id
        try:
            async with httpx.AsyncClient(
                base_url=self._settings.ai_service_url,
                timeout=self._settings.ai_service_timeout_seconds,
            ) as client:
                response = await client.post(
                    "/internal/intelligence/answers",
                    json=payload.model_dump(mode="json"),
                    headers=headers,
                )
        except httpx.HTTPError:
            raise ServiceUnavailableError("The answer service is unavailable.") from None
        if not 200 <= response.status_code < 300:
            raise ServiceUnavailableError("The answer service is unavailable.")
        try:
            return CrossMeetingQuestionResponse.model_validate(response.json())
        except Exception:
            raise ServiceUnavailableError("The answer service returned an invalid response.") from None


__all__ = ["AIServiceClient"]
