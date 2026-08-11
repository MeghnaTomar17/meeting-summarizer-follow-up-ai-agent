"""
Purpose: Consistent health-check responses for all FastAPI services.
Service ownership: Shared module.
"""

from __future__ import annotations

from shared.config.base import get_base_settings


def health_payload(service: str, version: str = "0.1.0") -> dict[str, str]:
    """Return a uniform liveness payload for Docker and load balancers."""
    settings = get_base_settings()
    return {
        "status": "ok",
        "service": service,
        "version": version,
        "environment": settings.app_env.value,
    }
