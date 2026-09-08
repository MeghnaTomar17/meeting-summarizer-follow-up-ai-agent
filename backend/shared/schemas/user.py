"""
Purpose: User domain schema and API DTOs.
Future responsibilities: Auth identity, roles, organization membership.
Service ownership: Shared (gateway-service primary consumer).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserBase(BaseModel):
    email: EmailStr


class UserCreate(UserBase):
    password: str = Field(min_length=8)


class UserUpdate(BaseModel):
    """The only currently supported self-service profile update."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class UserInDB(UserBase):
    id: str
    password_hash: str
    created_at: datetime
    updated_at: datetime

    # TODO: roles, is_active, last_login


class UserPublic(UserBase):
    id: str
    created_at: datetime
