"""
Purpose: Celery task — trigger AI summarization for a meeting.
Future responsibilities: Call ai-service pipeline, update meeting status.
Service ownership: worker-service.
"""

from __future__ import annotations

# TODO: @celery_app.task bind=True, max_retries=3


def run_summary_job(meeting_id: str) -> None:
    _ = meeting_id
    raise NotImplementedError
