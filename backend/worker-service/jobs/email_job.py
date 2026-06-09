"""
Purpose: Send scheduled follow-up and notification emails.
Future responsibilities: SMTP/SendGrid adapter, retry, dead letter.
Service ownership: worker-service.
"""

from __future__ import annotations


def run_email_job(followup_id: str) -> None:
    _ = followup_id
    raise NotImplementedError
