"""
Purpose: Worker service entry (optional HTTP for health/metrics).
Future responsibilities: Expose Celery flower proxy or health only.
Service ownership: worker-service.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(
    title="MannerAI Worker Service",
    version="0.1.0",
    description="Background jobs — Celery workers and schedulers.",
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "worker-service"}
