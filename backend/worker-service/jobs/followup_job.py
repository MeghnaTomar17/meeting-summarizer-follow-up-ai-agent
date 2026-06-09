"""
Purpose: Celery task — generate follow-up email draft.
Future responsibilities: Invoke ai-service followup pipeline.
Service ownership: worker-service.
"""

from __future__ import annotations


def run_followup_job(meeting_id: str) -> None:
    _ = meeting_id
    raise NotImplementedError
