"""
Purpose: Gateway public API v1 router aggregation point.
Future responsibilities: Mount auth, users, meetings, search, analytics, integrations.
Service ownership: gateway-service.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.routes.auth import router as auth_router
from app.routes.meetings import router as meetings_router
from app.routes.meeting_results import router as meeting_results_router
from app.routes.users import router as users_router
from shared.api.constants import API_V1_PREFIX

api_v1_router = APIRouter(prefix=API_V1_PREFIX)
api_v1_router.include_router(auth_router)
api_v1_router.include_router(meetings_router)
api_v1_router.include_router(meeting_results_router)
api_v1_router.include_router(users_router)

# Future business routers mount here, for example:
# api_v1_router.include_router(search.router)
# api_v1_router.include_router(analytics.router)
# api_v1_router.include_router(integrations.router)
