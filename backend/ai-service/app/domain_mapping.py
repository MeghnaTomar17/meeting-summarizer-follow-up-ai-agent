"""Deterministic mapping from typed AI outputs to existing domain inputs.

This module is an application boundary only: it has no database, repository,
provider, or service dependencies. Callers supply trusted meeting identity and
remain responsible for invoking the corresponding domain service.
"""

from __future__ import annotations

from typing import TypeVar
from uuid import UUID

from pydantic import BaseModel, ValidationError

from agents.decision_agent import DecisionAgentOutput
from agents.followup_agent import FollowUpAgentOutput
from agents.insight_agent import InsightAgentOutput
from agents.summary_agent import SummaryAgentOutput
from agents.task_agent import TaskAgentOutput
from shared.schemas.decision import DecisionBase
from shared.schemas.followup import FollowupBase
from shared.schemas.meeting_insight import MeetingInsightBase
from shared.schemas.summary import SummaryBase
from shared.schemas.task import TaskBase

TOutput = TypeVar("TOutput", bound=BaseModel)


class AIOutputMappingError(ValueError):
    """AI output cannot be represented safely by an existing domain input."""


def _trusted_meeting_id(meeting_id: UUID | str) -> str:
    try:
        return str(UUID(str(meeting_id)))
    except (TypeError, ValueError):
        raise AIOutputMappingError("Trusted meeting ID must be a valid UUID.") from None


def _validated_output(model: type[TOutput], output: TOutput) -> TOutput:
    try:
        if isinstance(output, model):
            # Revalidate a dump so even mutated/constructed model instances are
            # subject to the same strict contract as provider-produced data.
            return model.model_validate(output.model_dump())
        return model.model_validate(output)
    except (ValidationError, TypeError, ValueError):
        raise AIOutputMappingError("AI output does not match its typed contract.") from None


def map_summary_output(
    output: SummaryAgentOutput, *, meeting_id: UUID | str
) -> SummaryBase:
    value = _validated_output(SummaryAgentOutput, output)
    return SummaryBase(
        meeting_id=_trusted_meeting_id(meeting_id),
        content=value.content,
        key_topics=value.key_topics,
    )


def map_task_output(
    output: TaskAgentOutput, *, meeting_id: UUID | str
) -> list[TaskBase]:
    value = _validated_output(TaskAgentOutput, output)
    trusted_id = _trusted_meeting_id(meeting_id)
    tasks: list[TaskBase] = []
    for item in value.tasks:
        if item.due_date is not None:
            # The current domain accepts datetime, while AI supplies date only.
            # Do not manufacture a time or timezone to force the conversion.
            raise AIOutputMappingError(
                "Task due date cannot map to the current datetime domain contract."
            )
        # assignee_name remains available on the typed AI result; the current
        # domain accepts only a resolved assignee_id, so it remains unset here.
        tasks.append(
            TaskBase(
                meeting_id=trusted_id,
                title=item.title,
                description=item.description,
                assignee_id=None,
                due_at=None,
            )
        )
    return tasks


def map_decision_output(
    output: DecisionAgentOutput, *, meeting_id: UUID | str
) -> list[DecisionBase]:
    value = _validated_output(DecisionAgentOutput, output)
    trusted_id = _trusted_meeting_id(meeting_id)
    return [
        DecisionBase(
            meeting_id=trusted_id,
            statement=item.statement,
            context=item.context,
            participants=item.participants,
        )
        for item in value.decisions
    ]


def map_followup_output(
    output: FollowUpAgentOutput, *, meeting_id: UUID | str
) -> list[FollowupBase]:
    value = _validated_output(FollowUpAgentOutput, output)
    trusted_id = _trusted_meeting_id(meeting_id)
    followups: list[FollowupBase] = []
    for item in value.followups:
        if any(recipient.email is None for recipient in item.recipients):
            raise AIOutputMappingError(
                "Follow-up recipient names cannot map to the email-only domain contract."
            )
        # Only exact model-supplied addresses are used. Names are not converted
        # into addresses, and lifecycle fields are absent from FollowupBase.
        followups.append(
            FollowupBase(
                meeting_id=trusted_id,
                subject=item.subject,
                body_html=item.body_html,
                recipients=[recipient.email for recipient in item.recipients],
            )
        )
    return followups


def map_insight_output(
    output: InsightAgentOutput, *, meeting_id: UUID | str
) -> list[MeetingInsightBase]:
    """Map each validated candidate to an input for the insight domain."""
    value = _validated_output(InsightAgentOutput, output)
    trusted_id = _trusted_meeting_id(meeting_id)
    return [
        MeetingInsightBase(
            meeting_id=trusted_id,
            category=item.category,
            title=item.title,
            description=item.description,
        )
        for item in value.insights
    ]


__all__ = [
    "AIOutputMappingError",
    "map_summary_output",
    "map_task_output",
    "map_decision_output",
    "map_followup_output",
    "map_insight_output",
]
