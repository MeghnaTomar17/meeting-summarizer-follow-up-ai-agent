"""
Purpose: Consistent health-check responses for all FastAPI services.
Service ownership: Shared module.
"""

from __future__ import annotations

import os


def health_payload(service: str, version: str = "0.1.0") -> dict[str, str]:
    """Return a uniform liveness payload for Docker and load balancers."""
    return {
        "status": "ok",
        "service": service,
        "version": version,
        "environment": os.getenv("APP_ENV", "development"),
    }
