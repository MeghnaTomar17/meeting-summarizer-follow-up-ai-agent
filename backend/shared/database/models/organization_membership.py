"""Persisted organization membership and role assignments."""

from __future__ import annotations

import uuid
from enum import Enum

from sqlalchemy import CheckConstraint, Enum as SQLEnum, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, validates

from shared.database.base import Base
from shared.database.mixins import TimestampMixin


class OrganizationRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class OrganizationMembership(TimestampMixin, Base):
    __tablename__ = "organization_memberships"
    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'admin', 'member')",
            name="ck_organization_memberships_role",
        ),
        Index("ix_organization_memberships_user_id", "user_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[OrganizationRole] = mapped_column(
        SQLEnum(
            OrganizationRole,
            name="organization_membership_role",
            native_enum=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )

    @validates("role")
    def validate_role(self, _key: str, value: OrganizationRole | str) -> OrganizationRole:
        try:
            return OrganizationRole(value)
        except ValueError as error:
            raise ValueError("Unsupported organization membership role.") from error
