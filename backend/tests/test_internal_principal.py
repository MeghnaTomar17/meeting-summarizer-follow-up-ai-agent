"""Tests for signed Gateway-to-service authenticated principal assertions."""

from __future__ import annotations

import asyncio
import importlib
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.security import HTTPAuthorizationCredentials
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MEETING_ROOT = BACKEND_ROOT / "meeting-service"
_ALGORITHM = "RS256"


def _load_dependency_module():
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]
    while str(MEETING_ROOT) in sys.path:
        sys.path.remove(str(MEETING_ROOT))
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    sys.path.insert(0, str(MEETING_ROOT))
    return importlib.import_module("app.auth.dependencies")


class InternalPrincipalTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_dependency_module()
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.private_key = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        self.public_key = private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
        self.settings = SimpleNamespace(
            internal_principal_public_key=self.public_key,
            internal_principal_algorithm=_ALGORITHM,
            internal_principal_issuer="gateway-service",
            service_name="meeting-service",
        )
        from shared.exceptions.common import UnauthorizedError
        from shared.security.internal_principal import create_internal_principal

        self.UnauthorizedError = UnauthorizedError
        self.create_internal_principal = create_internal_principal

    @staticmethod
    def _credentials(token: str) -> HTTPAuthorizationCredentials:
        return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    def _valid_token(self, user_id: uuid.UUID) -> str:
        return self.create_internal_principal(
            user_id,
            private_key=self.private_key,
            algorithm=_ALGORITHM,
            issuer="gateway-service",
            audience="meeting-service",
            expires_seconds=60,
        )

    def _resolve(self, credentials: HTTPAuthorizationCredentials | None) -> uuid.UUID:
        with patch.object(self.module, "get_settings", return_value=self.settings):
            return asyncio.run(self.module.get_authenticated_user_id(credentials))

    def test_valid_gateway_principal_returns_only_user_uuid(self) -> None:
        user_id = uuid.uuid4()

        self.assertEqual(self._resolve(self._credentials(self._valid_token(user_id))), user_id)

    def test_expired_principal_is_rejected(self) -> None:
        user_id = uuid.uuid4()
        expired = jwt.encode(
            {
                "sub": str(user_id), "type": "internal_principal", "iss": "gateway-service",
                "aud": "meeting-service", "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
            }, self.private_key, algorithm=_ALGORITHM,
        )
        with self.assertRaises(self.UnauthorizedError):
            self._resolve(self._credentials(expired))

    def test_wrong_issuer_audience_type_and_invalid_uuid_are_rejected(self) -> None:
        user_id = uuid.uuid4()
        invalid_subject = jwt.encode(
            {
                "sub": "not-a-uuid", "type": "internal_principal", "iss": "gateway-service",
                "aud": "meeting-service", "exp": datetime.now(timezone.utc) + timedelta(minutes=1),
            }, self.private_key, algorithm=_ALGORITHM,
        )
        wrong_issuer = self.create_internal_principal(
            user_id, private_key=self.private_key, algorithm=_ALGORITHM,
            issuer="other-service", audience="meeting-service", expires_seconds=60,
        )
        wrong_audience = self.create_internal_principal(
            user_id, private_key=self.private_key, algorithm=_ALGORITHM,
            issuer="gateway-service", audience="other-service", expires_seconds=60,
        )
        wrong_type = jwt.encode(
            {
                "sub": str(user_id), "type": "access", "iss": "gateway-service",
                "aud": "meeting-service", "exp": datetime.now(timezone.utc) + timedelta(minutes=1),
            }, self.private_key, algorithm=_ALGORITHM,
        )

        for token in (invalid_subject, wrong_issuer, wrong_audience, wrong_type):
            with self.subTest(token=token[:12]), self.assertRaises(self.UnauthorizedError):
                self._resolve(self._credentials(token))

    def test_forged_different_signer_and_external_tokens_are_rejected(self) -> None:
        user_id = uuid.uuid4()
        different_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        forged = self.create_internal_principal(
            user_id,
            private_key=different_private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode(),
            algorithm=_ALGORITHM,
            issuer="gateway-service",
            audience="meeting-service",
            expires_seconds=60,
        )
        external_access_token = jwt.encode(
            {"sub": str(user_id), "type": "access", "exp": datetime.now(timezone.utc) + timedelta(minutes=1)},
            "external-secret", algorithm="HS256",
        )

        for token in ("not-a-token", forged, external_access_token):
            with self.subTest(token=token[:12]), self.assertRaises(self.UnauthorizedError):
                self._resolve(self._credentials(token))

    def test_meeting_settings_expose_only_the_public_verification_key(self) -> None:
        settings_module = importlib.import_module("app.config.settings")

        self.assertIn("internal_principal_public_key", settings_module.MeetingSettings.model_fields)
        self.assertNotIn(
            "internal_principal_private_key", settings_module.MeetingSettings.model_fields
        )

    def test_missing_credentials_are_rejected(self) -> None:
        with self.assertRaises(self.UnauthorizedError):
            self._resolve(None)

    def test_plain_client_identity_header_is_not_an_authentication_mechanism(self) -> None:
        with self.assertRaises(self.UnauthorizedError):
            self._resolve(None)
