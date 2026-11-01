"""Persist successful AI outputs as existing Meeting domain records."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.models.decision import Decision
from shared.database.models.followup import Followup
from shared.database.models.meeting import Meeting
from shared.database.models.meeting_insight import MeetingInsight
from shared.database.models.processing_job import ProcessingJobRecord
from shared.database.models.summary import Summary
from shared.database.models.task import Task
from shared.schemas.decision import DecisionBase
from shared.schemas.followup import FollowupBase
from shared.schemas.meeting_insight import MeetingInsightBase
from shared.schemas.summary import SummaryBase
from shared.schemas.task import TaskBase


async def persist_processing_result(
    session: AsyncSession,
    job: ProcessingJobRecord,
    result: dict[str, Any],
) -> None:
    """Write completed operation outputs without committing the caller's transaction.

    The worker calls this inside the same lifecycle transaction that stores the
    terminal job status and result JSON. A retry therefore cannot duplicate
    domain rows after a successful commit.
    """
    if not isinstance(result, dict):
        raise ValueError("Processing result must be an object.")
    if (
        _uuid(result.get("meeting_id")) != job.meeting_id
        or _uuid(result.get("transcript_id")) != job.transcript_id
        or result.get("requested_operations") != list(job.requested_operations)
    ):
        raise ValueError("Processing result identity does not match its job.")

    operations = result.get("results")
    if not isinstance(operations, list) or len(operations) != len(job.requested_operations):
        raise ValueError("Processing result operations do not match the registered job.")
    for expected, operation in zip(job.requested_operations, operations, strict=True):
        if not isinstance(operation, dict) or operation.get("operation") != expected:
            raise ValueError("Processing result operations do not match the registered job.")
        if operation.get("status") == "failed":
            continue
        if operation.get("status") != "completed":
            raise ValueError("Processing result operation status is invalid.")
        output = operation.get("output")
        if not isinstance(output, dict):
            raise ValueError("Completed processing output must be an object.")
        await _persist_operation(session, job.meeting_id, expected, output)

    await session.flush()


async def _persist_operation(
    session: AsyncSession,
    meeting_id: UUID,
    operation: str,
    output: dict[str, Any],
) -> None:
    if operation == "summary":
        payload = SummaryBase.model_validate(output)
        _require_meeting(payload.meeting_id, meeting_id)
        # Locking the meeting serializes version allocation across concurrent
        # successful jobs for this meeting.
        meeting = await session.execute(
            select(Meeting.id).where(Meeting.id == meeting_id).with_for_update()
        )
        if meeting.scalar_one_or_none() is None:
            raise ValueError("Processing result meeting is unavailable.")
        version = await session.scalar(
            select(func.coalesce(func.max(Summary.version), 0)).where(
                Summary.meeting_id == meeting_id
            )
        )
        session.add(
            Summary(
                meeting_id=meeting_id,
                content=payload.content,
                key_topics=payload.key_topics,
                model_provider=payload.model_provider,
                model_name=payload.model_name,
                version=int(version or 0) + 1,
            )
        )
        return

    if operation == "tasks":
        items = _validated_items(output, TaskBase)
        for item in items:
            _require_meeting(item.meeting_id, meeting_id)
            session.add(
                Task(
                    meeting_id=meeting_id,
                    title=item.title,
                    description=item.description,
                    assignee_id=_uuid(item.assignee_id) if item.assignee_id else None,
                    due_at=item.due_at,
                )
            )
        return

    if operation == "decisions":
        items = _validated_items(output, DecisionBase)
        for item in items:
            _require_meeting(item.meeting_id, meeting_id)
            session.add(
                Decision(
                    meeting_id=meeting_id,
                    statement=item.statement,
                    context=item.context,
                    participants=item.participants,
                )
            )
        return

    if operation == "follow_ups":
        items = _validated_items(output, FollowupBase)
        for item in items:
            _require_meeting(item.meeting_id, meeting_id)
            session.add(
                Followup(
                    meeting_id=meeting_id,
                    subject=item.subject,
                    body_html=item.body_html,
                    recipients=[str(address) for address in item.recipients],
                )
            )
        return

    if operation == "insights":
        items = _validated_items(output, MeetingInsightBase)
        for item in items:
            _require_meeting(item.meeting_id, meeting_id)
            session.add(
                MeetingInsight(
                    meeting_id=meeting_id,
                    category=item.category,
                    title=item.title,
                    description=item.description,
                )
            )
        return

    raise ValueError("Processing result contains an unsupported operation.")


def _validated_items(output: dict[str, Any], schema) -> list[Any]:
    raw_items = output.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("Processing result item collection is invalid.")
    return [schema.model_validate(item) for item in raw_items]


def _uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _require_meeting(value: str, expected: UUID) -> None:
    if _uuid(value) != expected:
        raise ValueError("Processing result output does not match its job meeting.")


__all__ = ["persist_processing_result"]
