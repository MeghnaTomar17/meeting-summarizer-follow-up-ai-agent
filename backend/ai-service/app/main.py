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
    description="Agents, LLM pipelines, summarization and extraction.",
)

register_logging_middleware(app)
register_exception_handlers(app)

# TODO: routes for on-demand processing (internal only)
# TODO: restrict to service mesh / internal network


@app.get("/health")
async def health() -> dict[str, str]:
    return health_payload("ai-service", version=app.version)


@app.get("/health/live")
async def health_live() -> dict[str, str]:
    return health_payload("ai-service", version=app.version)


@app.get("/health/ready")
async def health_ready() -> dict[str, str]:
    return health_payload("ai-service", version=app.version)
