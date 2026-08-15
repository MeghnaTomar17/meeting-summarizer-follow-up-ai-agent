"""
Purpose: FastAPI entrypoint for gateway-service.
Future responsibilities: Register routers, middleware, lifespan, OpenAPI.
Service ownership: gateway-service.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.api.v1.router import api_v1_router
from app.config.settings import get_settings
from app.openapi import configure_gateway_openapi
from shared.api.constants import API_V1_PREFIX
from shared.utils.health import health_payload
from shared.utils.service_bootstrap import (
    init_service_logging,
    register_exception_handlers,
    register_logging_middleware,
)

init_service_logging(get_settings)

app = FastAPI(
    title="MannerAI Meetings Platform API",
    version="0.1.0",
    description=(
        "Public API gateway for the MannerAI Meetings Platform. "
        f"Business endpoints are versioned under {API_V1_PREFIX}."
    ),
    servers=[{"url": API_V1_PREFIX, "description": "Public API v1"}],
    openapi_tags=[
        {"name": "auth", "description": "Authentication and session management"},
        {"name": "users", "description": "User profiles and administration"},
        {"name": "meetings", "description": "Meeting lifecycle and processing"},
        {"name": "search", "description": "Semantic search across meetings"},
        {"name": "analytics", "description": "Meeting analytics and reporting"},
        {"name": "integrations", "description": "Third-party integrations and webhooks"},
        {"name": "health", "description": "Infrastructure health probes"},
    ],
)

register_logging_middleware(app)
register_exception_handlers(app)
configure_gateway_openapi(app)

app.include_router(api_v1_router)

# TODO: include_router auth, users, meetings, search, analytics, integrations on api_v1_router
# TODO: CORS, rate limiting
# TODO: lifespan — postgres/redis init via shared.database


@app.get("/health", tags=["health"], include_in_schema=False)
async def health() -> dict[str, str]:
    """Liveness probe for Docker and load balancers."""
    return health_payload("gateway-service", version=app.version)


@app.get("/health/live", tags=["health"], include_in_schema=False)
async def health_live() -> dict[str, str]:
    """Kubernetes-style liveness probe."""
    return health_payload("gateway-service", version=app.version)


@app.get("/health/ready", tags=["health"], include_in_schema=False)
async def health_ready() -> dict[str, str]:
    """Readiness probe — dependency checks added in Phase 2."""
    return health_payload("gateway-service", version=app.version)
