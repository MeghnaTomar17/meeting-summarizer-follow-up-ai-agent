"""Organization and membership lookups owned by Meeting Service."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.models.organization import Organization
from shared.database.models.organization_membership import OrganizationMembership, OrganizationRole


class OrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_role(self, organization_id: UUID, user_id: UUID) -> OrganizationRole | None:
        statement = select(OrganizationMembership.role).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user_id,
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def get_personal_for_user(self, user_id: UUID) -> Organization | None:
        statement = (
            select(Organization)
            .join(OrganizationMembership, OrganizationMembership.organization_id == Organization.id)
            .where(
                Organization.personal_owner_user_id == user_id,
                OrganizationMembership.user_id == user_id,
                OrganizationMembership.role == OrganizationRole.OWNER,
            )
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()
