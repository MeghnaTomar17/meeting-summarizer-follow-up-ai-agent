"""Unit tests for atomic meeting-submission request and receipt contracts."""

from __future__ import annotations

import importlib
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MEETING_ROOT = BACKEND_ROOT / "meeting-service"
for path in (BACKEND_ROOT, MEETING_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


class MeetingSubmissionContractTestCase(unittest.TestCase):
    def setUp(self) -> None:
        from shared.schemas.meeting_submission import MeetingSubmissionRequest

        self.Request = MeetingSubmissionRequest
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        if str(MEETING_ROOT) in sys.path:
            sys.path.remove(str(MEETING_ROOT))
        sys.path.insert(0, str(MEETING_ROOT))
        self.MeetingService = importlib.import_module("app.services.meeting_service").MeetingService

    def _payload(self, **meeting_fields):
        meeting = {"organization_id": str(uuid.uuid4()), "title": "Planning"}
        meeting.update(meeting_fields)
        return {
            "meeting": meeting,
            "transcript": {
                "language": "en",
                "segments": [{"index": 0, "speaker": "A", "text": "Review the plan."}],
            },
            "requested_operations": ["summary", "summary", "tasks"],
        }

    def test_operations_are_deduplicated_and_client_owner_fields_are_rejected(self) -> None:
        payload = self.Request.model_validate(self._payload())
        self.assertEqual(payload.requested_operations, ["summary", "tasks"])
        with self.assertRaises(ValidationError):
            self.Request.model_validate(self._payload(created_by=str(uuid.uuid4())))
        malformed = self._payload()
        malformed["owner_id"] = str(uuid.uuid4())
        with self.assertRaises(ValidationError):
            self.Request.model_validate(malformed)

    def test_oversized_transcript_is_rejected_without_truncation(self) -> None:
        payload = self._payload()
        payload["transcript"]["segments"][0]["text"] = "x" * 100_001
        with self.assertRaisesRegex(ValidationError, "submission limit"):
            self.Request.model_validate(payload)

    def test_canonical_request_hash_ignores_json_key_order_and_timezone_offset(self) -> None:
        organization_id = uuid.uuid4()
        first = self.Request.model_validate(
            {
                "meeting": {
                    "organization_id": str(organization_id),
                    "title": "Planning",
                    "scheduled_at": "2026-10-31T12:00:00+05:30",
                },
                "transcript": {"segments": [{"index": 0, "text": "Review."}], "language": "en"},
                "requested_operations": ["summary"],
            }
        )
        equivalent = self.Request.model_validate(
            {
                "requested_operations": ["summary"],
                "transcript": {"language": "en", "segments": [{"text": "Review.", "index": 0}]},
                "meeting": {
                    "scheduled_at": "2026-10-31T06:30:00Z",
                    "title": "Planning",
                    "organization_id": str(organization_id),
                },
            }
        )
        digest = self.MeetingService._submission_payload_hash
        self.assertEqual(digest(first, organization_id), digest(equivalent, organization_id))

    def test_persistence_models_enforce_required_receipt_and_unique_outbox_job(self) -> None:
        from shared.database.models.job_outbox_event import JobOutboxEvent
        from shared.database.models.meeting_submission_idempotency import MeetingSubmissionIdempotency

        idem = MeetingSubmissionIdempotency.__table__
        for column in ("owner_id", "operation", "idempotency_key", "request_hash", "meeting_id", "transcript_id", "job_id"):
            self.assertFalse(idem.c[column].nullable)
        indexes = {index.name: index for index in idem.indexes}
        self.assertTrue(indexes["uq_meeting_submission_idempotency_owner_operation_key"].unique)
        outbox_indexes = {index.name: index for index in JobOutboxEvent.__table__.indexes}
        self.assertTrue(outbox_indexes["uq_job_outbox_events_job_id"].unique)


if __name__ == "__main__":
    unittest.main()
