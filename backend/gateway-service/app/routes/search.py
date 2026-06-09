"""
Purpose: Semantic search API routes (facade to search-service).
Future responsibilities: Query validation, auth scoping, result ranking.
Service ownership: gateway-service.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/search", tags=["search"])

# TODO: POST / — semantic search across meetings
# TODO: GET /suggestions — autocomplete placeholder
