"""Organization writes used during atomic account provisioning."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.models.organization import Organization
from shared.database.models.organization_membership import OrganizationMembership, OrganizationRole
from shared.database.models.user import User


class OrganizationProvisioningRepository:
    """Flush a new user's personal organization and owner membership."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_personal_for_user(self, user: User) -> Organization:
        organization = Organization(
            id=uuid4(),
            name="Personal workspace",
            personal_owner_user_id=user.id,
        )
        self._session.add(organization)
        await self._session.flush()
        self._session.add(
            OrganizationMembership(
                organization_id=organization.id,
                user_id=user.id,
                role=OrganizationRole.OWNER,
            )
        )
        await self._session.flush()
        return organization
