"""Phase 9.2 distributed job-identity and fail-closed security tests."""

from __future__ import annotations

import importlib
import base64
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

BACKEND_ROOT = Path(__file__).resolve().parents[1]
WORKER_ROOT = BACKEND_ROOT / "worker-service"
AI_ROOT = BACKEND_ROOT / "ai-service"
JOB_ID = UUID("50000000-0000-0000-0000-000000000005")
MEETING_ID = UUID("30000000-0000-0000-0000-000000000003")
TRANSCRIPT_ID = UUID("40000000-0000-0000-0000-000000000004")
USER_ID = UUID("10000000-0000-0000-0000-000000000001")


class Phase9_2JobAuthorizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.private_pem = cls.private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        cls.public_pem = cls.private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
        cls.other_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.other_private_pem = cls.other_private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        cls.other_public_pem = cls.other_private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
        sys.path[:0] = [str(BACKEND_ROOT), str(AI_ROOT)]
        cls.contract = importlib.import_module("shared.schemas.ai_job_envelope")
        cls.security = importlib.import_module(
            "shared.security.background_job_authorization"
        )

    @classmethod
    def tearDownClass(cls):
        for path in (str(BACKEND_ROOT), str(AI_ROOT), str(WORKER_ROOT)):
            while path in sys.path:
                sys.path.remove(path)

    def setUp(self):
        self.envelope = self.contract.AIProcessingJobEnvelope(
            job_id=JOB_ID,
            meeting_id=MEETING_ID,
            transcript_id=TRANSCRIPT_ID,
            requested_operations=["summary", "tasks"],
        )
        self.token = self.security.issue_job_authorization(
            self.envelope, USER_ID, private_key=self.private_pem
        )

    def _claims(self, **updates):
        now = datetime.now(timezone.utc)
        claims = {
            "sub": str(USER_ID),
            "type": "background_job_authorization",
            "iss": "ai-service",
            "aud": "mannerai-worker",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=60)).timestamp()),
            "jti": str(uuid4()),
            "job_id": str(JOB_ID),
            "meeting_id": str(MEETING_ID),
            "transcript_id": str(TRANSCRIPT_ID),
            "requested_operations": ["summary", "tasks"],
        }
        claims.update(updates)
        return claims

    def _signed(self, **updates):
        return jwt.encode(self._claims(**updates), self.private_pem, algorithm="RS256")

    def test_valid_authorization_returns_only_authenticated_subject(self):
        self.assertEqual(
            self.security.verify_job_authorization(
                self.token, self.envelope, public_key=self.public_pem
            ),
            USER_ID,
        )

    def test_every_binding_field_mismatch_is_rejected(self):
        fields = {
            "job_id": uuid4(),
            "meeting_id": uuid4(),
            "transcript_id": uuid4(),
        }
        for field, value in fields.items():
            with self.subTest(field=field), self.assertRaises(self.security.JobAuthorizationError):
                altered = self.envelope.model_copy(update={field: value})
                self.security.verify_job_authorization(
                    self.token, altered, public_key=self.public_pem
                )
        with self.assertRaises(self.security.JobAuthorizationError):
            altered = self.envelope.model_copy(update={"requested_operations": ["insights"]})
            self.security.verify_job_authorization(
                self.token, altered, public_key=self.public_pem
            )

    def test_signed_wrong_claims_and_invalid_lifetime_are_rejected(self):
        invalid_tokens = [
            self._signed(iss="untrusted-producer"),
            self._signed(aud="another-service"),
            self._signed(**{"type": "access"}),
            self._signed(exp=int(datetime.now(timezone.utc).timestamp()) - 30),
            self._signed(iat=int((datetime.now(timezone.utc) + timedelta(minutes=1)).timestamp())),
            self._signed(exp=int((datetime.now(timezone.utc) + timedelta(minutes=10)).timestamp())),
            self._signed(job_id=str(uuid4())),
            self._signed(meeting_id=str(uuid4())),
            self._signed(transcript_id=str(uuid4())),
            self._signed(requested_operations=["insights"]),
            self._signed(**{"jti": None}),
        ]
        for token in invalid_tokens:
            with self.subTest(token=token[:14]), self.assertRaises(
                self.security.JobAuthorizationError
            ):
                self.security.verify_job_authorization(
                    token, self.envelope, public_key=self.public_pem
                )

    def test_tampering_wrong_key_and_missing_or_malformed_credentials_fail(self):
        parts = self.token.split(".")
        tampered = parts[0] + "." + parts[1][:-1] + ("A" if parts[1][-1] != "A" else "B") + "." + parts[2]
        altered_claims = self._claims(sub=str(uuid4()))
        altered_payload = base64.urlsafe_b64encode(
            json.dumps(altered_claims, separators=(",", ":")).encode()
        ).decode().rstrip("=")
        modified_user = parts[0] + "." + altered_payload + "." + parts[2]
        cases = [
            ("tampered", tampered, self.public_pem),
            ("modified signed-subject bytes", modified_user, self.public_pem),
            ("wrong key", self.token, self.other_public_pem),
            ("malformed", "not-a-jwt", self.public_pem),
            ("empty", "", self.public_pem),
            ("missing verifier key", self.token, ""),
            ("malformed verifier key", self.token, "-----BEGIN PUBLIC KEY-----"),
        ]
        for label, token, key in cases:
            with self.subTest(label=label), self.assertRaises(self.security.JobAuthorizationError):
                self.security.verify_job_authorization(token, self.envelope, public_key=key)

    def test_same_valid_message_can_be_replayed_until_expiry_and_is_not_one_time(self):
        first = self.security.verify_job_authorization(
            self.token, self.envelope, public_key=self.public_pem
        )
        second = self.security.verify_job_authorization(
            self.token, self.envelope, public_key=self.public_pem
        )
        self.assertEqual(first, second)

    def test_invalid_worker_credentials_never_construct_job_or_invoke_executor(self):
        for name in list(sys.modules):
            if name == "app" or name.startswith("app.") or name == "jobs" or name.startswith("jobs.") or name.startswith("worker_queue"):
                del sys.modules[name]
        while str(AI_ROOT) in sys.path:
            sys.path.remove(str(AI_ROOT))
        while str(WORKER_ROOT) in sys.path:
            sys.path.remove(str(WORKER_ROOT))
        sys.path[:0] = [str(WORKER_ROOT), str(BACKEND_ROOT)]
        task = importlib.import_module("jobs.ai_processing_task")
        executor = SimpleNamespace(execute=AsyncMock())
        create_job = MagicMock()
        runtime = SimpleNamespace(
            executor=executor,
            verification_key=self.public_pem,
            authorization_issuer="ai-service",
            authorization_audience="mannerai-worker",
            authorization_max_age_seconds=120,
            create_job=create_job,
        )
        task.configure_job_execution(runtime)
        wire = {
            "envelope": self.envelope.model_dump(mode="json"),
            "authorization": self.token,
        }
        for field, value in (("job_id", str(uuid4())), ("meeting_id", str(uuid4())),
                             ("transcript_id", str(uuid4())),
                             ("requested_operations", ["insights"])):
            changed = json.loads(json.dumps(wire))
            changed["envelope"][field] = value
            with self.subTest(field=field), self.assertRaises(
                task.TrustedExecutionContextUnavailable
            ):
                task.execute_job_envelope(changed)
        bad = {"envelope": wire["envelope"], "authorization": self._signed(iss="attacker")}
        with self.assertRaises(task.TrustedExecutionContextUnavailable):
            task.execute_job_envelope(bad)
        self.assertEqual(create_job.call_count, 0)
        executor.execute.assert_not_awaited()

    def test_production_settings_reject_missing_and_malformed_keys(self):
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        while str(WORKER_ROOT) in sys.path:
            sys.path.remove(str(WORKER_ROOT))
        while str(AI_ROOT) in sys.path:
            sys.path.remove(str(AI_ROOT))
        sys.path.insert(0, str(AI_ROOT))
        ai_settings = importlib.import_module("app.config.settings")
        with self.assertRaises(ValueError):
            ai_settings.AISettings(_env_file=None, app_env="production")
        with self.assertRaises(ValueError):
            ai_settings.AISettings(
                _env_file=None,
                app_env="production",
                background_job_signing_private_key="not-a-key",
            )
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        while str(AI_ROOT) in sys.path:
            sys.path.remove(str(AI_ROOT))
        while str(WORKER_ROOT) in sys.path:
            sys.path.remove(str(WORKER_ROOT))
        sys.path[:0] = [str(WORKER_ROOT), str(BACKEND_ROOT)]
        worker_settings = importlib.import_module("app.config.settings")
        with self.assertRaises(ValueError):
            worker_settings.WorkerSettings(_env_file=None, app_env="production")
        with self.assertRaises(ValueError):
            worker_settings.WorkerSettings(
                _env_file=None,
                app_env="production",
                background_job_verification_public_key="invalid",
            )


if __name__ == "__main__":
    unittest.main()
