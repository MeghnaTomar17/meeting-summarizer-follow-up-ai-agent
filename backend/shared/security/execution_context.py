"""Minimal trusted identity context for deferred application work."""

from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


class TrustedExecutionContext(BaseModel):
    """Authenticated Gateway principal carried across an internal job boundary.

    Gateway auth issues request contexts after ``get_current_user`` validates
    credentials and loads the persisted row. The worker may issue one only
    after verifying a purpose-specific signed job authorization. This value
    contains no credentials and is not a public request schema.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: UUID
    context_id: UUID = Field(default_factory=uuid4)
    _issued_by_authenticated_boundary: bool = PrivateAttr(default=False)

    @classmethod
    def _issue_from_authenticated_user_id(
        cls, user_id: UUID
    ) -> "TrustedExecutionContext":
        """Internal Gateway issuance hook; callers must use the auth dependency."""
        if not isinstance(user_id, UUID):
            raise TypeError("An authenticated user UUID is required.")
        context = cls(user_id=user_id)
        object.__setattr__(context, "_issued_by_authenticated_boundary", True)
        return context

    @property
    def was_issued_by_authenticated_boundary(self) -> bool:
        return self._issued_by_authenticated_boundary


__all__ = ["TrustedExecutionContext"]
