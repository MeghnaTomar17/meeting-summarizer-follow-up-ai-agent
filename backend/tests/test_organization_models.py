"""Organization persistence contract tests (no database required)."""

from __future__ import annotations

import asyncio
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.models.organization import Organization
from shared.database.models.organization_membership import OrganizationMembership, OrganizationRole

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MEETING_ROOT = BACKEND_ROOT / "meeting-service"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


class OrganizationModelTestCase(unittest.TestCase):
    def setUp(self) -> None:
        for key in list(sys.modules):
            if key == "app" or key.startswith("app."):
                del sys.modules[key]
        while str(MEETING_ROOT) in sys.path:
            sys.path.remove(str(MEETING_ROOT))
        sys.path.insert(0, str(MEETING_ROOT))

    def test_organization_has_unique_personal_owner_and_user_foreign_key(self) -> None:
        table = Organization.__table__
        constraints = {constraint.name: constraint for constraint in table.constraints}
        self.assertIn("uq_organizations_personal_owner_user_id", constraints)
        personal_fk = next(
            fk for fk in table.c.personal_owner_user_id.foreign_keys
        )
        self.assertEqual(personal_fk.target_fullname, "users.id")
        self.assertEqual(personal_fk.ondelete, "CASCADE")
        self.assertTrue(table.c.personal_owner_user_id.nullable)

    def test_membership_uses_unique_pair_foreign_keys_and_supported_roles(self) -> None:
        table = OrganizationMembership.__table__
        self.assertEqual(
            {column.name for column in table.primary_key.columns},
            {"organization_id", "user_id"},
        )
        foreign_keys = {
            foreign_key.target_fullname: foreign_key
            for column in table.columns
            for foreign_key in column.foreign_keys
        }
        self.assertEqual(set(foreign_keys), {"organizations.id", "users.id"})
        self.assertTrue(all(foreign_key.ondelete == "CASCADE" for foreign_key in foreign_keys.values()))
        self.assertEqual(
            {role.value for role in OrganizationRole}, {"owner", "admin", "member"}
        )
        membership = OrganizationMembership(
            organization_id=uuid.uuid4(), user_id=uuid.uuid4(), role="admin"
        )
        self.assertEqual(membership.role, OrganizationRole.ADMIN)
        second = OrganizationMembership(
            organization_id=uuid.uuid4(), user_id=membership.user_id, role="member"
        )
        self.assertNotEqual(membership.organization_id, second.organization_id)

    def test_invalid_role_is_rejected_by_model_validation(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported organization membership role"):
            OrganizationMembership(
                organization_id=uuid.uuid4(), user_id=uuid.uuid4(), role="guest"
            )

    def test_repository_scopes_membership_lookup_to_both_ids(self) -> None:
        from app.repositories.organization_repository import OrganizationRepository

        session = MagicMock(spec=AsyncSession)
        session.execute = AsyncMock(
            return_value=SimpleNamespace(
                scalar_one_or_none=MagicMock(return_value=OrganizationRole.ADMIN)
            )
        )
        repository = OrganizationRepository(session)
        organization_id, user_id = uuid.uuid4(), uuid.uuid4()
        result = asyncio.run(repository.get_role(organization_id, user_id))
        self.assertEqual(result, OrganizationRole.ADMIN)
        statement = str(session.execute.await_args.args[0])
        self.assertIn("organization_memberships.organization_id", statement)
        self.assertIn("organization_memberships.user_id", statement)
