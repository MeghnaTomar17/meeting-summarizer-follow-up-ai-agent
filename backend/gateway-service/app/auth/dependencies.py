"""
Purpose: FastAPI dependencies for current user and permissions.
Future responsibilities: get_current_user, require_role, org scope.
Service ownership: gateway-service.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict[str, str]:
    """Resolve authenticated user — TODO: decode JWT and load from DB."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    raise NotImplementedError
