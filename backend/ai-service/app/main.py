"""
Purpose: FastAPI entrypoint for ai-service.
Future responsibilities: Expose pipeline triggers, agent status, health.
Service ownership: ai-service.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.config.settings import get_settings
from shared.utils.health import health_payload
from shared.utils.service_bootstrap import (
    init_service_logging,
    register_exception_handlers,
    register_logging_middleware,
)

init_service_logging(get_settings)

app = FastAPI(
    title="MannerAI AI Service",
    version="0.1.0",
    description="Internal AI processing foundation; provider execution is not implemented.",
)

register_logging_middleware(app)
register_exception_handlers(app)

# Processing routes are deferred until the internal invocation/authentication
# contract is defined. This service is not mounted on the public Gateway.


@app.get("/health")
async def health() -> dict[str, str]:
    return health_payload("ai-service", version=app.version)


@app.get("/health/live")
async def health_live() -> dict[str, str]:
    return health_payload("ai-service", version=app.version)


@app.get("/health/ready")
async def health_ready() -> dict[str, str]:
    return health_payload("ai-service", version=app.version)
