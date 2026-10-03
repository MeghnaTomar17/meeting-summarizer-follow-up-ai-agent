"""Celery infrastructure configuration for worker-service."""

from __future__ import annotations

from celery import Celery
from celery.signals import worker_init

from app.config.settings import WorkerSettings, get_settings


def create_celery_app(settings: WorkerSettings | None = None) -> Celery:
    """Create a configured app without opening a broker or backend connection."""
    settings = settings or get_settings()
    app = Celery(
        "mannerai-worker",
        broker=str(settings.celery_broker_url),
        backend=None,
        include=("jobs.ai_processing_task",),
    )
    app.conf.update(
        task_serializer=settings.celery_task_serializer,
        result_serializer=settings.celery_result_serializer,
        accept_content=list(settings.celery_accept_content),
        timezone=settings.celery_timezone,
        enable_utc=True,
        task_acks_late=settings.celery_task_acks_late,
        task_reject_on_worker_lost=settings.celery_task_reject_on_worker_lost,
        worker_prefetch_multiplier=settings.celery_worker_prefetch_multiplier,
        worker_concurrency=settings.celery_worker_concurrency,
        broker_connection_timeout=settings.celery_broker_connection_timeout,
        broker_connection_retry_on_startup=True,
        broker_transport_options={
            "socket_connect_timeout": settings.celery_broker_socket_connect_timeout,
            "socket_timeout": settings.celery_broker_socket_timeout,
            "retry_on_timeout": True,
        },
        task_ignore_result=True,
    )
    return app


celery_app = create_celery_app()


@worker_init.connect(weak=False)
def configure_ai_job_runtime_on_worker_start(**_: object) -> None:
    """Load execution dependencies at worker startup, never at module import."""
    from jobs.ai_processing_task import (
        configure_job_execution,
        is_job_execution_configured,
    )

    # Integration harnesses can install a deterministic runtime before the
    # worker starts; regular workers receive the environment-backed runtime.
    if is_job_execution_configured():
        return
    from jobs.runtime import create_worker_job_runtime

    configure_job_execution(create_worker_job_runtime(get_settings()))

__all__ = ["create_celery_app", "celery_app"]
