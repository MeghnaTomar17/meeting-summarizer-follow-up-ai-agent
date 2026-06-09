"""
Purpose: Internal meeting CRUD routes.
Future responsibilities: Persistence via repositories, status transitions.
Service ownership: meeting-service.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/meetings", tags=["meetings"])

# TODO: CRUD endpoints used by gateway-service
