"""
Purpose: FastAPI entrypoint for search-service.
Future responsibilities: Semantic search, indexing status, internal APIs.
Service ownership: search-service.
"""

from __future__ import annotations

from fastapi import FastAPI

from shared.utils.health import health_payload

app = FastAPI(
    title="MannerAI Search Service",
    version="0.1.0",
    description="Embedding generation, semantic retrieval, vector search.",
)

# TODO: include_router from routes/


@app.get("/health")
async def health() -> dict[str, str]:
    return health_payload("search-service", version=app.version)


@app.get("/health/live")
async def health_live() -> dict[str, str]:
    return health_payload("search-service", version=app.version)


@app.get("/health/ready")
async def health_ready() -> dict[str, str]:
    return health_payload("search-service", version=app.version)
