"""
Purpose: FastAPI entrypoint for meeting-service.
Future responsibilities: Upload routes, meeting CRUD, transcript APIs.
Service ownership: meeting-service.
"""

from __future__ import annotations

from fastapi import FastAPI

from shared.utils.health import health_payload

app = FastAPI(
    title="MannerAI Meeting Service",
    version="0.1.0",
    description="Meeting CRUD, transcript storage, upload and audio processing.",
)

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
