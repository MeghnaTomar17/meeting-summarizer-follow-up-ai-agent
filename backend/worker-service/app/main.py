"""
Purpose: Worker service entry (optional HTTP for health/metrics).
Future responsibilities: Expose Celery flower proxy or health only.
Service ownership: worker-service.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.config.settings import get_settings
from shared.utils.health import health_payload
from shared.utils.service_bootstrap import init_service_logging, register_logging_middleware

init_service_logging(get_settings)

app = FastAPI(
    title="MannerAI Worker Service",
    version="0.1.0",
    description="Background jobs — Celery workers and schedulers.",
)

register_logging_middleware(app)


@app.get("/health")
async def health() -> dict[str, str]:
    return health_payload("worker-service", version=app.version)


@app.get("/health/live")
async def health_live() -> dict[str, str]:
    return health_payload("worker-service", version=app.version)


@app.get("/health/ready")
async def health_ready() -> dict[str, str]:
    return health_payload("worker-service", version=app.version)
