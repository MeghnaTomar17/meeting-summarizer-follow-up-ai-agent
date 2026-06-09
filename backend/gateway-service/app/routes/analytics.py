"""
Purpose: Meeting analytics and reporting APIs.
Future responsibilities: Aggregates, trends, team dashboards.
Service ownership: gateway-service.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/analytics", tags=["analytics"])

# TODO: GET /overview
# TODO: GET /meetings/{meeting_id}/insights
# TODO: GET /teams/{org_id}/metrics
