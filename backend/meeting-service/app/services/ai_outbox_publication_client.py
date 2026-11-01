"""Authenticated AI Service client for outbox publication requests."""

from __future__ import annotations

import json
from uuid import UUID

import httpx

from app.config.settings import MeetingSettings
from shared.jobs.outbox_policy import (
    OutboxFailureCategory,
    OutboxPublicationError,
)
from shared.schemas.outbox_publication import (
    OutboxPublicationRequest,
    OutboxPublicationResponse,
)
from shared.schemas.ai_job_envelope import AIProcessingJobEnvelope
from shared.security.service_principal import (
    OUTBOX_PUBLICATION_AUDIENCE,
    OUTBOX_PUBLICATION_ISSUER,
    create_service_principal,
)


class AIOutboxPublicationClient:
    """Use Meeting Service's dedicated identity; never holds the AI job key."""

    def __init__(
        self,
        settings: MeetingSettings,
        *,
        request_id: str | None = None,
    ) -> None:
        self._settings = settings
        self._request_id = request_id

    async def publish_outbox_event(
        self,
        *,
        event_id: UUID,
        owner_id: UUID,
        job_id: UUID,
        event_type: str,
        payload: dict[str, object],
    ) -> None:
        private_key = self._settings.outbox_publication_auth_private_key
        if private_key is None:
            raise OutboxPublicationError(OutboxFailureCategory.CONFIGURATION_INVALID)
        try:
            envelope = AIProcessingJobEnvelope.model_validate_json(
                json.dumps(payload, allow_nan=False, separators=(",", ":"))
            )
            request = OutboxPublicationRequest(
                event_id=event_id,
                owner_id=owner_id,
                job_id=job_id,
                event_type=event_type,
                payload=envelope,
            )
        except Exception:
            raise OutboxPublicationError(OutboxFailureCategory.EVENT_INVALID) from None
        try:
            principal = create_service_principal(
                "meeting-service",
                private_key=private_key.get_secret_value().replace("\\n", "\n"),
                issuer=OUTBOX_PUBLICATION_ISSUER,
                audience=OUTBOX_PUBLICATION_AUDIENCE,
                expires_seconds=60,
            )
        except Exception:
            raise OutboxPublicationError(OutboxFailureCategory.CONFIGURATION_INVALID) from None

        headers = {"Authorization": f"Bearer {principal}"}
        if self._request_id:
            headers["X-Request-ID"] = self._request_id
        try:
            async with httpx.AsyncClient(
                base_url=self._settings.ai_service_url,
                timeout=self._settings.ai_service_timeout_seconds,
            ) as client:
                response = await client.post(
                    "/internal/jobs/outbox-events",
                    json=request.model_dump(mode="json"),
                    headers=headers,
                )
        except httpx.HTTPError:
            raise OutboxPublicationError(
                OutboxFailureCategory.PUBLICATION_OUTCOME_UNKNOWN
            ) from None
        if response.status_code != 202:
            raise OutboxPublicationError(self._failure_category(response))
        try:
            receipt = OutboxPublicationResponse.model_validate(response.json())
        except Exception:
            raise OutboxPublicationError(
                OutboxFailureCategory.PUBLICATION_OUTCOME_UNKNOWN
            ) from None
        if receipt.event_id != event_id or receipt.job_id != job_id:
            raise OutboxPublicationError(
                OutboxFailureCategory.PUBLICATION_OUTCOME_UNKNOWN
            )

    @staticmethod
    def _failure_category(response: httpx.Response) -> OutboxFailureCategory:
        """Classify only allow-listed status/code metadata; ignore response text."""
        if response.status_code in {401, 403}:
            return OutboxFailureCategory.AUTHENTICATION_REJECTED
        if response.status_code in {400, 422}:
            return OutboxFailureCategory.REQUEST_REJECTED
        try:
            error = response.json().get("error", {})
            code = error.get("code") if isinstance(error, dict) else None
        except (ValueError, TypeError, AttributeError):
            code = None
        if response.status_code == 408 or response.status_code >= 500:
            if code == f"outbox_{OutboxFailureCategory.CONFIGURATION_INVALID.value}":
                return OutboxFailureCategory.CONFIGURATION_INVALID
            return OutboxFailureCategory.PUBLICATION_OUTCOME_UNKNOWN
        if response.status_code == 429:
            return OutboxFailureCategory.BROKER_UNAVAILABLE
        if isinstance(code, str) and code.startswith("outbox_"):
            candidate = code.removeprefix("outbox_")
            try:
                category = OutboxFailureCategory(candidate)
            except ValueError:
                category = None
            if category is not None:
                return category
        return OutboxFailureCategory.REQUEST_REJECTED


__all__ = ["AIOutboxPublicationClient"]
