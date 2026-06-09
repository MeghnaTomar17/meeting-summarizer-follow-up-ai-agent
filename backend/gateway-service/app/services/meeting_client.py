"""
Purpose: HTTP client for meeting-service.
Future responsibilities: Typed calls for CRUD, uploads, transcript fetch.
Service ownership: gateway-service.
"""

from __future__ import annotations

from typing import Any


class MeetingServiceClient:
    """Async httpx client wrapper — TODO: inject base_url from settings."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url

    async def list_meetings(self, organization_id: str, page: int = 1) -> dict[str, Any]:
        """List meetings — TODO: implement."""
        _ = (organization_id, page)
        raise NotImplementedError
