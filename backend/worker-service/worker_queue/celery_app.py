"""Celery infrastructure configuration for worker-service."""

from __future__ import annotations

from celery import Celery

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
        task_ignore_result=True,
    )
    return app


celery_app = create_celery_app()

__all__ = ["create_celery_app", "celery_app"]
