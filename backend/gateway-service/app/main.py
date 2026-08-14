"""
Purpose: FastAPI entrypoint for gateway-service.
Future responsibilities: Register routers, middleware, lifespan, OpenAPI.
Service ownership: gateway-service.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.config.settings import get_settings
from shared.utils.health import health_payload
from shared.utils.service_bootstrap import init_service_logging, register_logging_middleware

init_service_logging(get_settings)

app = FastAPI(
    title="MannerAI Gateway Service",
    version="0.1.0",
    description="Authentication, API routing, validation, analytics and integrations.",
)

register_logging_middleware(app)

# TODO: include_router auth, users, meetings, search, analytics, integrations
# TODO: CORS, rate limiting
# TODO: lifespan — postgres/redis init via shared.database


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe for Docker and load balancers."""
    return health_payload("gateway-service", version=app.version)


@app.get("/health/live")
async def health_live() -> dict[str, str]:
    """Kubernetes-style liveness probe."""
    return health_payload("gateway-service", version=app.version)


@app.get("/health/ready")
async def health_ready() -> dict[str, str]:
    """Readiness probe — dependency checks added in Phase 2."""
    return health_payload("gateway-service", version=app.version)
