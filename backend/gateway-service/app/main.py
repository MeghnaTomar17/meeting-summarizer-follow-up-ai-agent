"""
Purpose: FastAPI entrypoint for gateway-service.
Future responsibilities: Register routers, middleware, lifespan, OpenAPI.
Service ownership: gateway-service.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(
    title="MannerAI Gateway Service",
    version="0.1.0",
    description="Authentication, API routing, validation, analytics and integrations.",
)

# TODO: include_router auth, users, meetings, search, analytics, integrations
# TODO: CORS, rate limiting, request ID middleware
# TODO: lifespan — postgres/redis init via shared.database


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe placeholder."""
    return {"status": "ok", "service": "gateway-service"}
