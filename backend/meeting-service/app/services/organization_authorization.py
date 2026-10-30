"""Meeting Service organization authorization from verified principals."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from app.repositories.organization_repository import OrganizationRepository
from shared.database.models.organization_membership import OrganizationRole
from shared.exceptions.common import ForbiddenError


class OrganizationPermission(StrEnum):
    SUBMIT_MEETING = "submit_meeting"


class OrganizationAuthorization:
    def __init__(self, repository: OrganizationRepository) -> None:
        self._repository = repository

    async def require(
        self,
        user_id: UUID,
        organization_id: UUID,
        permission: OrganizationPermission,
    ) -> OrganizationRole:
        role = await self._repository.get_role(organization_id, user_id)
        if role is None:
            raise ForbiddenError()
        if permission is OrganizationPermission.SUBMIT_MEETING and role not in {
            OrganizationRole.OWNER,
            OrganizationRole.ADMIN,
            OrganizationRole.MEMBER,
        }:
            raise ForbiddenError()
        return role
