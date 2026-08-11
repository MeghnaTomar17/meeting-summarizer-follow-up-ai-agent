"""
Purpose: Celery application configuration.
Future responsibilities: Broker, result backend, task routes, beat schedule.
Service ownership: worker-service.
"""

from __future__ import annotations

# TODO: from celery import Celery
# TODO: celery_app = Celery("mannerai", broker=..., backend=...)
# TODO: autodiscover_tasks from jobs/

celery_app = None  # placeholder
