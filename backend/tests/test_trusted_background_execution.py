"""Security tests for authenticated context propagation to transcript access."""

from __future__ import annotations

import importlib
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

BACKEND_ROOT = Path(__file__).resolve().parents[1]
AI_ROOT = BACKEND_ROOT / "ai-service"
MEETING_ROOT = BACKEND_ROOT / "meeting-service"
GATEWAY_ROOT = BACKEND_ROOT / "gateway-service"
USER_A = UUID("10000000-0000-0000-0000-000000000001")
USER_B = UUID("20000000-0000-0000-0000-000000000002")
MEETING_ID = UUID("30000000-0000-0000-0000-000000000003")
TRANSCRIPT_ID = UUID("40000000-0000-0000-0000-000000000004")


def _clear_service_modules() -> None:
    for name in list(sys.modules):
        if any(name == package or name.startswith(f"{package}.") for package in ("app", "agents", "llm")):
            del sys.modules[name]


class TrustedBackgroundExecutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _clear_service_modules()
        for path in (str(AI_ROOT), str(MEETING_ROOT), str(BACKEND_ROOT)):
            while path in sys.path:
                sys.path.remove(path)
        sys.path[:0] = [str(BACKEND_ROOT), str(AI_ROOT)]
        self.jobs = importlib.import_module("app.background_processing")
        self.contracts = importlib.import_module("app.contracts")
        self.results = importlib.import_module("app.processing_results")

        _clear_service_modules()
        while str(AI_ROOT) in sys.path:
            sys.path.remove(str(AI_ROOT))
        sys.path.insert(0, str(MEETING_ROOT))
        self.meeting_module = importlib.import_module("app.services.meeting_service")
        self.provider_module = importlib.import_module(
            "app.services.transcript_input_provider"
        )
        self.models = importlib.import_module("shared.database.models.meeting")
        self.transcript_model = importlib.import_module(
            "shared.database.models.transcript"
        )
        self.user_model = importlib.import_module("shared.database.models.user").User
        self.context_type = importlib.import_module(
            "shared.security.execution_context"
        ).TrustedExecutionContext
        self.transcript_schema = importlib.import_module("shared.schemas.transcript")
        self.summary_schema = importlib.import_module("shared.schemas.summary")
        self.errors = importlib.import_module("shared.exceptions.common")

    def _context(self, user_id: UUID):
        return self.context_type._issue_from_authenticated_user_id(user_id)

    def _job_and_result(self, user_id: UUID):
        job = self.jobs.AIProcessingJob.from_authenticated_context(
            meeting_id=MEETING_ID,
            transcript_id=TRANSCRIPT_ID,
            requested_operations=[self.contracts.ProcessingOperation.SUMMARY],
            execution_context=self._context(user_id),
        )
        result = self.results.AIProcessingResult(
            meeting_id=MEETING_ID,
            transcript_id=TRANSCRIPT_ID,
            requested_operations=job.requested_operations,
            status=self.contracts.ProcessingStatus.COMPLETED,
            results=[
                self.results.MappedOperationResult(
                    operation=self.contracts.ProcessingOperation.SUMMARY,
                    status=self.results.OperationStatus.COMPLETED,
                    output=self.summary_schema.SummaryBase(
                        meeting_id=str(MEETING_ID), content="Summary", key_topics=[]
                    ),
                )
            ],
        )
        return job, result

    def _service(self, owner_id: UUID):
        meeting = self.models.Meeting(
            id=MEETING_ID,
            organization_id=UUID(int=55),
            created_by=owner_id,
            title="Planning",
            status=self.models.MeetingStatus.PENDING,
        )
        transcript = self.transcript_model.Transcript(
            id=TRANSCRIPT_ID,
            meeting_id=MEETING_ID,
            segments=[{"index": 0, "speaker": "Ari", "text": "Plan."}],
            language="en",
        )
        now = datetime.now(timezone.utc)
        meeting.created_at = now
        meeting.updated_at = now
        transcript.created_at = now
        transcript.updated_at = now
        meetings = MagicMock()
        meetings.get_by_id = AsyncMock(return_value=meeting)
        transcripts = MagicMock()
        transcripts.get_by_meeting_id = AsyncMock(return_value=transcript)
        service = self.meeting_module.MeetingService(
            session=MagicMock(),
            meeting_repository=meetings,
            transcript_repository=transcripts,
        )
        return service, meetings, transcripts

    async def test_owned_transcript_uses_existing_meeting_service_authorization(self):
        job, result = self._job_and_result(USER_A)
        service, meetings, transcripts = self._service(USER_A)
        provider = self.provider_module.MeetingServiceTranscriptInputProvider(service)
        ai_service = AsyncMock()
        ai_service.process.return_value = result
        executor = self.jobs.AIProcessingJobExecutorService(ai_service, provider)

        finished = await executor.execute(job)

        self.assertEqual(finished.status, self.jobs.AIProcessingJobStatus.COMPLETED)
        meetings.get_by_id.assert_awaited_once_with(MEETING_ID)
        transcripts.get_by_meeting_id.assert_awaited_once_with(MEETING_ID)
        ai_service.process.assert_awaited_once()

    async def test_wrong_user_is_rejected_by_existing_ownership_check(self):
        job, _ = self._job_and_result(USER_B)
        service, meetings, transcripts = self._service(USER_A)
        provider = self.provider_module.MeetingServiceTranscriptInputProvider(service)
        ai_service = AsyncMock()
        executor = self.jobs.AIProcessingJobExecutorService(ai_service, provider)

        finished = await executor.execute(job)

        self.assertEqual(finished.status, self.jobs.AIProcessingJobStatus.FAILED)
        self.assertEqual(finished.failure.code, self.jobs.JobFailureCode.EXECUTION_FAILED)
        meetings.get_by_id.assert_awaited_once_with(MEETING_ID)
        transcripts.get_by_meeting_id.assert_not_awaited()
        ai_service.process.assert_not_awaited()

    async def test_transcript_id_is_checked_after_meeting_service_authorization(self):
        job, _ = self._job_and_result(USER_A)
        service, meetings, transcripts = self._service(USER_A)
        provider = self.provider_module.MeetingServiceTranscriptInputProvider(service)

        with self.assertRaises(self.errors.NotFoundError):
            await provider.get_transcript(
                MEETING_ID, UUID(int=99), job.execution_context
            )

        meetings.get_by_id.assert_awaited_once_with(MEETING_ID)
        transcripts.get_by_meeting_id.assert_awaited_once_with(MEETING_ID)

    async def test_gateway_context_dependency_is_downstream_of_current_user(self):
        _clear_service_modules()
        while str(MEETING_ROOT) in sys.path:
            sys.path.remove(str(MEETING_ROOT))
        sys.path.insert(0, str(GATEWAY_ROOT))
        auth = importlib.import_module("app.auth.dependencies")
        dependency = auth.get_trusted_execution_context
        current_user_dependency = dependency.__defaults__[0].dependency
        self.assertIs(current_user_dependency, auth.get_current_user)

        user = self.user_model(
            id=USER_A, email="gateway-user@example.test", password_hash="hash"
        )
        execution_context = await dependency(current_user=user)
        self.assertEqual(execution_context.user_id, USER_A)


if __name__ == "__main__":
    unittest.main()
