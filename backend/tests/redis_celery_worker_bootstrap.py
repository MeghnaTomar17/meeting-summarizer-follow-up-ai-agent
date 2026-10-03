"""Test-only Celery worker bootstrap for the opt-in Redis integration test."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
WORKER_ROOT = BACKEND_ROOT / "worker-service"
for _root in (str(BACKEND_ROOT), str(WORKER_ROOT)):
    if _root not in sys.path:
        sys.path.insert(0, _root)

from worker_queue.celery_app import celery_app
from worker_queue.redis_client import get_sync_redis_url


def _import_service_types(service_root: Path, module_map: dict[str, tuple[str, ...]]):
    previous_path = list(sys.path)
    previous_app_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "app" or name.startswith("app.")
    }
    try:
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        for root in (str(BACKEND_ROOT / "ai-service"), str(BACKEND_ROOT / "meeting-service"), str(WORKER_ROOT)):
            while root in sys.path:
                sys.path.remove(root)
        sys.path.insert(0, str(service_root))
        values: dict[str, Any] = {}
        for module_name, attributes in module_map.items():
            module = __import__(module_name, fromlist=list(attributes))
            values.update({attribute: getattr(module, attribute) for attribute in attributes})
        return values
    finally:
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        sys.modules.update(previous_app_modules)
        sys.path[:] = previous_path


_ai = _import_service_types(
    BACKEND_ROOT / "ai-service",
    {
        "app.background_processing": ("AIProcessingJob", "AIProcessingJobExecutorService"),
        "app.processing_service": ("AIProcessingService",),
        "app.contracts": ("ModelResponse",),
        "agents.orchestrator": ("AIProcessingOrchestrator",),
    },
)
_meeting = _import_service_types(
    BACKEND_ROOT / "meeting-service",
    {
        "app.services.meeting_service": ("MeetingService",),
        "app.services.transcript_input_provider": ("MeetingServiceTranscriptInputProvider",),
    },
)

MEETING_ID = UUID("30000000-0000-0000-0000-000000000003")
TRANSCRIPT_ID = UUID("40000000-0000-0000-0000-000000000004")
USER_ID = UUID("10000000-0000-0000-0000-000000000001")
REPORT_KEY = os.environ["MANNERAI_REDIS_TEST_REPORT_KEY"]


class _DeterministicProvider:
    response_type = _ai["ModelResponse"]

    async def generate(self, request):
        schema_title = request.response_schema["title"]
        output = {
            "SummaryAgentOutput": {
                "content": "Redis Celery integration summary",
                "key_topics": ["integration"],
            },
            "TaskAgentOutput": {"tasks": []},
        }[schema_title]
        return self.response_type(content=json.dumps(output))


class _ReportingExecutor:
    def __init__(self) -> None:
        self.provider = _DeterministicProvider()

    async def execute(self, job):
        from redis import Redis

        meeting = SimpleNamespace(id=MEETING_ID, created_by=USER_ID)
        transcript = SimpleNamespace(
            id=TRANSCRIPT_ID,
            meeting_id=MEETING_ID,
            language="en",
            segments=[{"index": 0, "speaker": "Ari", "text": "Test the launch plan."}],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        class MeetingRepository:
            async def get_by_id(self, meeting_id):
                return meeting if meeting_id == MEETING_ID else None

        class TranscriptRepository:
            async def get_by_meeting_id(self, meeting_id):
                return transcript if meeting_id == MEETING_ID else None

        meeting_service = _meeting["MeetingService"](
            object(), MeetingRepository(), TranscriptRepository()
        )
        transcript_provider = _meeting["MeetingServiceTranscriptInputProvider"](
            meeting_service
        )
        processing_service = _ai["AIProcessingService"](
            _ai["AIProcessingOrchestrator"](self.provider)
        )
        executor = _ai["AIProcessingJobExecutorService"](
            processing_service, transcript_provider
        )
        completed = await executor.execute(job)
        report = {
            "job_id": str(completed.job_id),
            "meeting_id": str(completed.meeting_id),
            "transcript_id": str(completed.transcript_id),
            "requested_operations": [item.value for item in completed.requested_operations],
            "user_id": str(completed.execution_principal_id),
            "status": completed.status.value,
        }
        Redis.from_url(get_sync_redis_url(), decode_responses=True).set(
            REPORT_KEY, json.dumps(report), ex=120
        )
        return completed


def _create_job(envelope, execution_context):
    return _ai["AIProcessingJob"].from_authenticated_context(
        job_id=envelope.job_id,
        meeting_id=envelope.meeting_id,
        transcript_id=envelope.transcript_id,
        requested_operations=list(envelope.requested_operations),
        execution_context=execution_context,
    )


from jobs.ai_processing_task import configure_job_execution
from app.config.settings import get_settings

_settings = get_settings()
configure_job_execution(
    SimpleNamespace(
        executor=_ReportingExecutor(),
        verification_key=(
            _settings.background_job_verification_public_key.get_secret_value()
            if _settings.background_job_verification_public_key
            else ""
        ),
        authorization_issuer=_settings.background_job_issuer,
        authorization_audience=_settings.background_job_audience,
        authorization_max_age_seconds=_settings.background_job_authorization_max_age_seconds,
        create_job=_create_job,
    )
)
