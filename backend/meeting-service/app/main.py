"""
Purpose: FastAPI entrypoint for meeting-service.
Future responsibilities: Upload routes, meeting CRUD, transcript APIs.
Service ownership: meeting-service.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.config.settings import get_settings
from shared.utils.health import health_payload
from shared.utils.service_bootstrap import init_service_logging, register_logging_middleware

init_service_logging(get_settings)

app = FastAPI(
    title="MannerAI Meeting Service",
    version="0.1.0",
    description="Meeting CRUD, transcript storage, upload and audio processing.",
)

register_logging_middleware(app)

# TODO: include_router upload, meetings, transcripts
# TODO: lifespan — postgres, object storage


@app.get("/health")
async def health() -> dict[str, str]:
    return health_payload("meeting-service", version=app.version)


@app.get("/health/live")
async def health_live() -> dict[str, str]:
    return health_payload("meeting-service", version=app.version)


@app.get("/health/ready")
async def health_ready() -> dict[str, str]:
    return health_payload("meeting-service", version=app.version)
