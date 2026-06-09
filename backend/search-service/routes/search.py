"""
Purpose: Search HTTP routes.
Future responsibilities: Query embedding, Qdrant search, filter by org.
Service ownership: search-service.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/search", tags=["search"])

# TODO: POST / — semantic search
# TODO: POST /index — upsert chunks (internal, from worker)
