"""
Purpose: Authentication HTTP routes (login, register, refresh, logout).
Future responsibilities: JWT issuance, OAuth callbacks, session invalidation.
Service ownership: gateway-service.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/auth", tags=["auth"])

# TODO: POST /register
# TODO: POST /login
# TODO: POST /refresh
# TODO: POST /logout
