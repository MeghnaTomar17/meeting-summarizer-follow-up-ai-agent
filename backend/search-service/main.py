"""
Purpose: FastAPI entrypoint for search-service.
Future responsibilities: Semantic search, indexing status, internal APIs.
Service ownership: search-service.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(
    title="MannerAI Search Service",
    version="0.1.0",
    description="Embedding generation, semantic retrieval, vector search.",
)

# TODO: include_router from routes/


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "search-service"}
