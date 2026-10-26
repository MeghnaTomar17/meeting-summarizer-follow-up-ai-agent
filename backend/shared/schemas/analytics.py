"""Typed response contracts for owner-scoped dashboard analytics."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from shared.jobs.lifecycle import JobStatus
from shared.schemas.followup import FollowupStatus
from shared.schemas.meeting import MeetingStatus

DEFAULT_ANALYTICS_WEEKS = 12
MAX_ANALYTICS_WEEKS = 52
DEFAULT_TOPICS_PER_WEEK = 10
MAX_TOPICS_PER_WEEK = 25
MAX_RECURRING_BLOCKERS = 50
MAX_BLOCKER_EVIDENCE_PER_GROUP = 100
DEFAULT_SPEAKER_MEETING_LIMIT = 50
MAX_SPEAKER_MEETING_LIMIT = 100
MAX_SPEAKERS_PER_MEETING = 50


class WeeklyMeetingCount(BaseModel):
    """Count of meetings scheduled during a UTC calendar week."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    week_start: date
    count: int = Field(ge=0)


class AnalyticsOverviewResponse(BaseModel):
    """Current dashboard totals plus a bounded UTC weekly meeting series."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    total_meetings: int = Field(ge=0)
    meetings_per_week: list[WeeklyMeetingCount]
    open_tasks: int = Field(ge=0)
    completed_tasks: int = Field(ge=0)
    overdue_tasks: int = Field(ge=0)
    decisions: int = Field(ge=0)
    followups: int = Field(ge=0)
    followup_status_counts: dict[FollowupStatus, int]
    meeting_status_counts: dict[MeetingStatus, int]
    processing_job_status_counts: dict[JobStatus, int]


class WeeklyDecisionCount(BaseModel):
    """Count of persisted decisions created during a UTC calendar week."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    week_start: date
    count: int = Field(ge=0)


class TopicTrendCount(BaseModel):
    """Number of owned scheduled meetings whose latest summary lists a topic."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    topic: str = Field(min_length=1, max_length=500)
    count: int = Field(ge=1)


class WeeklyTopicTrend(BaseModel):
    """Top normalized exact topic strings for one UTC calendar week."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    week_start: date
    topics: list[TopicTrendCount] = Field(max_length=MAX_TOPICS_PER_WEEK)


class AnalyticsTrendsResponse(BaseModel):
    """Bounded weekly decision, meeting-frequency, and topic trends."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_trends: list[WeeklyDecisionCount]
    meeting_frequency: list[WeeklyMeetingCount]
    topic_trends: list[WeeklyTopicTrend]


class BlockerEvidenceReference(BaseModel):
    """Persisted blocker insight and meeting identifiers with original text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    meeting_id: UUID
    insight_id: UUID
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    insight_created_at: datetime


class RecurringBlocker(BaseModel):
    """Exact normalized-description group backed by distinct meetings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    group_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    description: str = Field(min_length=1)
    meeting_count: int = Field(ge=2)
    evidence_count: int = Field(ge=2)
    evidence_truncated: bool
    evidence: list[BlockerEvidenceReference] = Field(
        min_length=2, max_length=MAX_BLOCKER_EVIDENCE_PER_GROUP
    )


class RecurringBlockersResponse(BaseModel):
    """Bounded owner-scoped recurring blocker groups with persisted provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    recurring_blockers: list[RecurringBlocker] = Field(
        max_length=MAX_RECURRING_BLOCKERS
    )


class TaskCompletionTrendsResponse(BaseModel):
    """Capability response; historical completion events are not persisted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    available: Literal[False] = False
    reason: str = Field(min_length=1, max_length=500)


class SpeakerCount(BaseModel):
    """Attributed valid transcript segment count for one meeting-local label."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    speaker: str = Field(min_length=1, max_length=500)
    segment_count: int = Field(ge=1)


class MeetingSpeakerParticipation(BaseModel):
    """Segment-count participation for one owned persisted transcript."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    meeting_id: UUID
    transcript_id: UUID
    segment_count: int = Field(ge=0)
    unknown_speaker_segment_count: int = Field(ge=0)
    speakers: list[SpeakerCount] = Field(max_length=MAX_SPEAKERS_PER_MEETING)
    speakers_truncated: bool


class SpeakerParticipationResponse(BaseModel):
    """Bounded per-meeting counts; speaker labels are not linked across meetings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    total_transcripts: int = Field(ge=0)
    meetings: list[MeetingSpeakerParticipation] = Field(
        max_length=MAX_SPEAKER_MEETING_LIMIT
    )
    truncated: bool


__all__ = [
    "AnalyticsOverviewResponse",
    "AnalyticsTrendsResponse",
    "BlockerEvidenceReference",
    "RecurringBlocker",
    "RecurringBlockersResponse",
    "MAX_BLOCKER_EVIDENCE_PER_GROUP",
    "MAX_RECURRING_BLOCKERS",
    "DEFAULT_SPEAKER_MEETING_LIMIT",
    "MAX_SPEAKER_MEETING_LIMIT",
    "MAX_SPEAKERS_PER_MEETING",
    "MeetingSpeakerParticipation",
    "SpeakerCount",
    "SpeakerParticipationResponse",
    "TaskCompletionTrendsResponse",
    "DEFAULT_TOPICS_PER_WEEK",
    "DEFAULT_ANALYTICS_WEEKS",
    "MAX_TOPICS_PER_WEEK",
    "MAX_ANALYTICS_WEEKS",
    "TopicTrendCount",
    "WeeklyDecisionCount",
    "WeeklyMeetingCount",
    "WeeklyTopicTrend",
]
