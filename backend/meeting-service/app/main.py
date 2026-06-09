"""
Purpose: FastAPI entrypoint for meeting-service.
Future responsibilities: Upload routes, meeting CRUD, transcript APIs.
Service ownership: meeting-service.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(
    title="MannerAI Meeting Service",
    version="0.1.0",
    description="Meeting CRUD, transcript storage, upload and audio processing.",
)

# TODO: include_router upload, meetings, transcripts
# TODO: lifespan — postgres, object storage


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "meeting-service"}
