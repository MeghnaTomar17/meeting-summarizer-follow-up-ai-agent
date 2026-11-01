"""Explicit Meeting Service command to publish at most one outbox event.

Run from the Meeting Service container with:
    python -m app.outbox_dispatch_once

This command is deliberately separate from API startup and Worker Service.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone

from app.config.settings import get_settings
from app.database import shutdown_database, startup_database
from app.services.job_outbox_runtime import (
    OneShotOutboxStatus,
    create_one_shot_outbox_runtime,
)
from shared.middleware.request_logging import resolve_request_id

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def run_outbox_dispatch_once():
    """Initialize Meeting Service resources and invoke the existing runtime once."""
    settings = get_settings()
    primary_error: BaseException | None = None
    try:
        await startup_database(settings)
        request_id = resolve_request_id(None)
        runtime = create_one_shot_outbox_runtime(
            settings=settings,
            request_id=request_id,
        )
        locked_until = _utc_now() + timedelta(
            seconds=settings.processing_job_lease_seconds
        )
        return await runtime.run_once(locked_until=locked_until)
    except BaseException as error:
        primary_error = error
        raise
    finally:
        try:
            await shutdown_database()
        except BaseException as cleanup_error:
            if primary_error is None:
                raise
            primary_error.add_note(
                "Meeting Service database shutdown also failed "
                f"({type(cleanup_error).__name__})."
            )
            logger.error(
                "outbox_dispatch_database_shutdown_failed",
                extra={"error_type": type(cleanup_error).__name__},
            )


def main() -> int:
    """CLI entry point; keep exception text (which may contain secrets) private."""
    try:
        result = asyncio.run(run_outbox_dispatch_once())
    except Exception as error:
        logger.error(
            "outbox_dispatch_once_failed",
            extra={"error_type": type(error).__name__},
        )
        print(
            f"Outbox dispatch failed ({type(error).__name__}); see service logs.",
            file=sys.stderr,
        )
        return 1

    if result.status == OneShotOutboxStatus.NO_WORK:
        print("Outbox dispatch complete: no eligible event.")
    elif result.status == OneShotOutboxStatus.EXHAUSTED:
        print(
            "Outbox dispatch complete: publication attempts exhausted for event "
            f"{result.event_id}; operator action is required."
        )
    elif result.status == OneShotOutboxStatus.AMBIGUOUS_EXHAUSTED:
        print(
            "Outbox dispatch complete: ambiguous publication recovery exhausted for event "
            f"{result.event_id}; operator action is required."
        )
    else:
        print(f"Outbox dispatch complete: published event {result.event_id}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
