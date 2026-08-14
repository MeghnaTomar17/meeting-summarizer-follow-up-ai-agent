"""
Purpose: FastAPI entrypoint for search-service.
Future responsibilities: Semantic search, indexing status, internal APIs.
Service ownership: search-service.
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
    title="MannerAI Search Service",
    version="0.1.0",
    description="Embedding generation, semantic retrieval, vector search.",
)

register_logging_middleware(app)
register_exception_handlers(app)

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
