"""Worker composition root for verified AI jobs and the Phase 8 executor."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config.settings import WorkerSettings
from shared.schemas.ai_job_envelope import AIProcessingJobEnvelope
from shared.security.execution_context import TrustedExecutionContext
from shared.jobs.lifecycle import PostgresJobLifecycle
from shared.jobs.lifecycle import JobTargetRejectedError
from shared.exceptions.common import ForbiddenError, NotFoundError


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_service_types() -> dict[str, Any]:
    """Import service packages in isolation; each backend owns an ``app`` name."""
    backend = _backend_root()
    original_path = list(sys.path)
    original_app_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "app" or name.startswith("app.")
    }

    def import_from(service: str, modules: dict[str, tuple[str, ...]]) -> dict[str, Any]:
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        service_root = str(backend / service)
        for root in (str(backend / "worker-service"), str(backend / "ai-service"), str(backend / "meeting-service")):
            while root in sys.path:
                sys.path.remove(root)
        sys.path.insert(0, service_root)
        found: dict[str, Any] = {}
        for module_name, attributes in modules.items():
            module = importlib.import_module(module_name)
            for attribute in attributes:
                found[attribute] = getattr(module, attribute)
        return found

    try:
        ai_types = import_from(
            "ai-service",
            {
                "app.config.settings": ("get_settings",),
                "app.background_processing": (
                    "AIProcessingJob",
                    "AIProcessingJobExecutorService",
                ),
                "app.processing_service": ("AIProcessingService",),
                "agents.orchestrator": ("AIProcessingOrchestrator",),
                "llm.openai_client": ("OpenAIModelProvider",),
            },
        )
        meeting_types = import_from(
            "meeting-service",
            {
                "app.repositories.meeting_repository": ("MeetingRepository",),
                "app.repositories.transcript_repository": ("TranscriptRepository",),
                "app.services.meeting_service": ("MeetingService",),
                "app.services.transcript_input_provider": (
                    "MeetingServiceTranscriptInputProvider",
                ),
            },
        )
        return {**ai_types, **meeting_types, "backend_root": backend}
    finally:
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        sys.modules.update(original_app_modules)
        sys.path[:] = original_path


class _Phase8ExecutorAdapter:
    """Create per-job DB/provider resources and delegate to the Phase 8 executor."""

    def __init__(self, settings: WorkerSettings, service_types: dict[str, Any]) -> None:
        self._settings = settings
        self._types = service_types
        self._ai_settings = service_types["get_settings"]()

    async def authorize_target(self, job: Any) -> None:
        """Run MeetingService ownership/transcript checks before lifecycle claim."""
        engine = create_async_engine(
            self._settings.database_url,
            pool_pre_ping=True,
            echo=self._settings.database_echo,
            poolclass=NullPool,
        )
        try:
            session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
            async with session_factory() as session:
                meeting_service = self._types["MeetingService"](
                    session,
                    self._types["MeetingRepository"](session),
                    self._types["TranscriptRepository"](session),
                )
                transcript_provider = self._types["MeetingServiceTranscriptInputProvider"](meeting_service)
                try:
                    await transcript_provider.get_transcript(
                        job.meeting_id,
                        job.transcript_id,
                        job.execution_context,
                    )
                except ForbiddenError:
                    raise JobTargetRejectedError() from None
                except NotFoundError:
                    from shared.jobs.lifecycle import FailureCategory

                    raise JobTargetRejectedError(FailureCategory.PERMANENT_VALIDATION) from None
        finally:
            await engine.dispose()

    async def execute(self, job: Any) -> Any:
        engine = create_async_engine(
            self._settings.database_url,
            pool_pre_ping=True,
            echo=self._settings.database_echo,
            poolclass=NullPool,
        )
        provider = self._types["OpenAIModelProvider"](
            api_key=self._ai_settings.openai_api_key,
            model=self._ai_settings.openai_model,
            timeout_seconds=self._ai_settings.openai_timeout_seconds,
        )
        session_factory = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )
        try:
            async with session_factory() as session:
                meeting_service = self._types["MeetingService"](
                    session,
                    self._types["MeetingRepository"](session),
                    self._types["TranscriptRepository"](session),
                )
                transcript_provider = self._types[
                    "MeetingServiceTranscriptInputProvider"
                ](meeting_service)
                processing_service = self._types["AIProcessingService"](
                    self._types["AIProcessingOrchestrator"](provider)
                )
                executor = self._types["AIProcessingJobExecutorService"](
                    processing_service, transcript_provider
                )
                return await executor.execute(job)
        finally:
            await provider.aclose()
            await engine.dispose()


def create_worker_job_runtime(settings: WorkerSettings) -> object:
    """Compose production worker dependencies without connecting at startup."""
    service_types = _load_service_types()
    job_type = service_types["AIProcessingJob"]
    public_key: str | None = None
    configured_key: SecretStr | None = settings.background_job_verification_public_key
    if configured_key is not None:
        public_key = configured_key.get_secret_value()

    def create_job(
        envelope: AIProcessingJobEnvelope,
        execution_context: TrustedExecutionContext,
    ) -> Any:
        return job_type.from_authenticated_context(
            job_id=envelope.job_id,
            meeting_id=envelope.meeting_id,
            transcript_id=envelope.transcript_id,
            requested_operations=list(envelope.requested_operations),
            execution_context=execution_context,
        )

    executor = _Phase8ExecutorAdapter(settings, service_types)
    return type(
        "WorkerJobExecutionRuntime",
        (),
        {
            "executor": executor,
            "authorize_target": executor.authorize_target,
            "lifecycle": PostgresJobLifecycle(settings),
            "verification_key": public_key or "",
            "authorization_issuer": settings.background_job_issuer,
            "authorization_audience": settings.background_job_audience,
            "authorization_max_age_seconds": settings.background_job_authorization_max_age_seconds,
            "create_job": staticmethod(create_job),
        },
    )()


__all__ = ["create_worker_job_runtime"]
