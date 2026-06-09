"""
Purpose: Third-party integration routes (calendar, email, Zoom, etc.).
Future responsibilities: OAuth connect, webhooks, sync triggers.
Service ownership: gateway-service.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/integrations", tags=["integrations"])

# TODO: GET /providers
# TODO: POST /calendar/connect
# TODO: POST /gmail/connect
# TODO: POST /webhooks/{provider}
