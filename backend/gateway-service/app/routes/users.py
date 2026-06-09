"""
Purpose: User profile and administration routes.
Future responsibilities: CRUD profile, org membership, preferences.
Service ownership: gateway-service.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/users", tags=["users"])

# TODO: GET /me
# TODO: PATCH /me
# TODO: GET /{user_id} (admin)
