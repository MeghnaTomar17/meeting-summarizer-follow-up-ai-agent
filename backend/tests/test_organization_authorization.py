"""Organization membership authorization unit tests."""

from __future__ import annotations

import asyncio
import importlib
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MEETING_ROOT = BACKEND_ROOT / "meeting-service"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


class OrganizationAuthorizationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        for key in list(sys.modules):
            if key == "app" or key.startswith("app."):
                del sys.modules[key]
        while str(MEETING_ROOT) in sys.path:
            sys.path.remove(str(MEETING_ROOT))
        sys.path.insert(0, str(MEETING_ROOT))
        from app.repositories.organization_repository import OrganizationRepository
        from app.services.organization_authorization import (
            OrganizationAuthorization,
            OrganizationPermission,
        )
        from shared.database.models.organization_membership import OrganizationRole

        self.repository = AsyncMock(spec=OrganizationRepository)
        self.authorization = OrganizationAuthorization(self.repository)
        self.Permission = OrganizationPermission
        self.Role = OrganizationRole
        self.user_id = uuid.uuid4()
        self.organization_id = uuid.uuid4()

    def test_all_approved_roles_can_submit(self) -> None:
        for role in (self.Role.OWNER, self.Role.ADMIN, self.Role.MEMBER):
            with self.subTest(role=role):
                self.repository.get_role.return_value = role
                result = asyncio.run(
                    self.authorization.require(
                        self.user_id,
                        self.organization_id,
                        self.Permission.SUBMIT_MEETING,
                    )
                )
                self.assertEqual(result, role)

    def test_nonmember_and_unknown_organization_are_forbidden(self) -> None:
        from shared.exceptions.common import ForbiddenError

        self.repository.get_role.return_value = None
        with self.assertRaises(ForbiddenError):
            asyncio.run(
                self.authorization.require(
                    self.user_id,
                    self.organization_id,
                    self.Permission.SUBMIT_MEETING,
                )
            )

    def test_meeting_creator_identity_does_not_bypass_membership_lookup(self) -> None:
        from shared.exceptions.common import ForbiddenError

        # Even if the caller happens to own a meeting in this organization,
        # authorization receives only the verified user and membership result.
        self.repository.get_role.return_value = None
        with self.assertRaises(ForbiddenError):
            asyncio.run(
                self.authorization.require(
                    self.user_id,
                    self.organization_id,
                    self.Permission.SUBMIT_MEETING,
                )
            )
        self.repository.get_role.assert_awaited_once_with(
            self.organization_id, self.user_id
        )

    def test_membership_query_uses_verified_user_and_organization(self) -> None:
        self.repository.get_role.return_value = self.Role.MEMBER
        asyncio.run(
            self.authorization.require(
                self.user_id,
                self.organization_id,
                self.Permission.SUBMIT_MEETING,
            )
        )
        self.repository.get_role.assert_awaited_once_with(
            self.organization_id, self.user_id
        )
