"""
Purpose: Auth-related API schemas.
Future responsibilities: LoginRequest, TokenResponse, RefreshRequest.
Service ownership: gateway-service.
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
