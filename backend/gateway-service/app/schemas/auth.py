"""
Purpose: Auth-related API schemas.
Future responsibilities: LoginRequest, TokenResponse, RefreshRequest.
Service ownership: gateway-service.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str = Field(min_length=1, max_length=512)


class LogoutRequest(RefreshRequest):
    pass


class LogoutResponse(BaseModel):
    success: bool = True
