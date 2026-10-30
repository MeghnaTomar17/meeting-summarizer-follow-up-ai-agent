"""Persisted organizations and personal-organization ownership markers."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.database.base import Base
from shared.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizations"
    __table_args__ = (
        UniqueConstraint("personal_owner_user_id", name="uq_organizations_personal_owner_user_id"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    # Nullable for future non-personal organizations. This is a provisioning
    # marker, not an authorization grant; membership rows remain authoritative.
    personal_owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
