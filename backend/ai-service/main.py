"""
Purpose: FastAPI entrypoint for ai-service.
Future responsibilities: Expose pipeline triggers, agent status, health.
Service ownership: ai-service.
"""

from __future__ import annotations

from fastapi import FastAPI

from shared.utils.health import health_payload

app = FastAPI(
    title="MannerAI AI Service",
    version="0.1.0",
    description="Agents, LLM pipelines, summarization and extraction.",
)

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
