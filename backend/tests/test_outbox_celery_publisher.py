"""Signed Celery publication contract for durable outbox events."""

from __future__ import annotations

import importlib
import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

BACKEND_ROOT = Path(__file__).resolve().parents[1]
AI_ROOT = BACKEND_ROOT / "ai-service"
MEETING_ID = UUID("30000000-0000-0000-0000-000000000003")
TRANSCRIPT_ID = UUID("40000000-0000-0000-0000-000000000004")
JOB_ID = UUID("50000000-0000-0000-0000-000000000005")
EVENT_ID = UUID("60000000-0000-0000-0000-000000000006")
OWNER_ID = UUID("10000000-0000-0000-0000-000000000001")


async def _immediate_to_thread(function, *args, **kwargs):
    return function(*args, **kwargs)


def _drive_immediate(coroutine):
    try:
        return coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("Fake Celery publisher unexpectedly suspended.")


class OutboxCeleryPublisherTests(unittest.TestCase):
    def setUp(self) -> None:
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        for root in (str(AI_ROOT), str(BACKEND_ROOT)):
            while root in sys.path:
                sys.path.remove(root)
        sys.path[:0] = [str(BACKEND_ROOT), str(AI_ROOT)]
        self.envelope_type = importlib.import_module(
            "shared.schemas.ai_job_envelope"
        ).AIProcessingJobEnvelope
        submission_module = importlib.import_module("app.celery_submission")
        self.port_type = submission_module.CeleryJobSubmissionPort
        self.error_type = submission_module.CelerySubmissionError
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.private_pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        self.public_pem = key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

    def _payload(self):
        return self.envelope_type(
            job_id=JOB_ID,
            meeting_id=MEETING_ID,
            transcript_id=TRANSCRIPT_ID,
            requested_operations=["summary", "tasks"],
        ).model_dump(mode="json")

    def test_signed_publication_and_duplicate_delivery_keep_stable_identity(self) -> None:
        publisher = MagicMock()
        publisher.send_task.return_value = SimpleNamespace(id=str(JOB_ID))
        port = self.port_type(publisher, signing_key=self.private_pem)
        payload = self._payload()

        with patch.object(asyncio, "to_thread", new=_immediate_to_thread):
            for _ in range(2):
                _drive_immediate(
                    port.publish_outbox_event(
                        event_id=EVENT_ID,
                        owner_id=OWNER_ID,
                        job_id=JOB_ID,
                        event_type="ai.processing.requested.v1",
                        payload=payload,
                    )
                )

        self.assertEqual(publisher.send_task.call_count, 2)
        first, second = publisher.send_task.call_args_list
        self.assertEqual(first.args[0], "mannerai.process_ai_job")
        self.assertEqual(first.kwargs["task_id"], str(JOB_ID))
        self.assertEqual(first.kwargs["headers"]["outbox_event_id"], str(EVENT_ID))
        self.assertEqual(second.kwargs["headers"]["outbox_event_id"], str(EVENT_ID))
        message = first.kwargs["args"][0]
        self.assertEqual(message["envelope"], payload)
        claims = jwt.decode(
            message["authorization"],
            self.public_pem,
            algorithms=["RS256"],
            issuer="ai-service",
            audience="mannerai-worker",
        )
        self.assertEqual(claims["sub"], str(OWNER_ID))
        self.assertEqual(claims["job_id"], str(JOB_ID))
        self.assertEqual(claims["meeting_id"], str(MEETING_ID))
        self.assertEqual(claims["transcript_id"], str(TRANSCRIPT_ID))
        self.assertNotIn(self.private_pem, str(message))

    def test_broker_failure_is_sanitized_and_does_not_ack(self) -> None:
        publisher = MagicMock()
        publisher.send_task.side_effect = ConnectionError(
            "redis://worker:secret@broker.internal:6379/1"
        )
        port = self.port_type(publisher, signing_key=self.private_pem)

        with patch.object(asyncio, "to_thread", new=_immediate_to_thread):
            with self.assertRaises(self.error_type) as raised:
                _drive_immediate(
                    port.publish_outbox_event(
                        event_id=EVENT_ID,
                        owner_id=OWNER_ID,
                        job_id=JOB_ID,
                        event_type="ai.processing.requested.v1",
                        payload=self._payload(),
                    )
                )

        self.assertNotIn("secret", str(raised.exception))
        self.assertNotIn("broker.internal", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
