"""Application use case for authenticated dashboard analytics."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable
from uuid import UUID

from app.repositories.analytics_repository import AnalyticsRepository
from shared.jobs.lifecycle import JobStatus
from shared.schemas.analytics import (
    DEFAULT_ANALYTICS_WEEKS,
    DEFAULT_TOPICS_PER_WEEK,
    DEFAULT_SPEAKER_MEETING_LIMIT,
    MAX_TOPICS_PER_WEEK,
    MAX_SPEAKER_MEETING_LIMIT,
    MAX_ANALYTICS_WEEKS,
    AnalyticsOverviewResponse,
    AnalyticsTrendsResponse,
    BlockerEvidenceReference,
    RecurringBlocker,
    RecurringBlockersResponse,
    SpeakerCount,
    SpeakerParticipationResponse,
    MeetingSpeakerParticipation,
    TaskCompletionTrendsResponse,
    TopicTrendCount,
    WeeklyDecisionCount,
    WeeklyMeetingCount,
    WeeklyTopicTrend,
)
from shared.schemas.followup import FollowupStatus
from shared.schemas.meeting import MeetingStatus
from shared.schemas.task import TaskStatus

class AnalyticsService:
    """Build a bounded UTC calendar-week response from repository aggregates."""

    def __init__(
        self,
        repository: AnalyticsRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def overview(
        self, owner_id: UUID, *, weeks: int = DEFAULT_ANALYTICS_WEEKS
    ) -> AnalyticsOverviewResponse:
        now, first_week_start, start, end = self._week_window(weeks)

        values = await self._repository.get_overview(
            owner_id, week_start=start, week_end=end, as_of=now
        )
        weekly_counts = {
            row[0].date() if isinstance(row[0], datetime) else row[0]: row[1]
            for row in values["weekly_rows"]
        }
        meetings_per_week = [
            WeeklyMeetingCount(
                week_start=first_week_start + timedelta(weeks=index),
                count=weekly_counts.get(
                    first_week_start + timedelta(weeks=index), 0
                ),
            )
            for index in range(weeks)
        ]

        task_counts = values["task_counts"]
        followup_counts = values["followup_counts"]
        meeting_status_counts = values["meeting_status_counts"]
        job_status_counts = values["processing_job_status_counts"]
        return AnalyticsOverviewResponse(
            total_meetings=values["total_meetings"],
            meetings_per_week=meetings_per_week,
            open_tasks=sum(
                task_counts.get(status, 0)
                for status in (TaskStatus.OPEN, TaskStatus.IN_PROGRESS)
            ),
            completed_tasks=task_counts.get(TaskStatus.DONE, 0),
            overdue_tasks=values["overdue_tasks"],
            decisions=values["decisions"],
            followups=sum(followup_counts.values()),
            followup_status_counts={
                status: followup_counts.get(status, 0) for status in FollowupStatus
            },
            meeting_status_counts={
                status: meeting_status_counts.get(status, 0) for status in MeetingStatus
            },
            processing_job_status_counts={
                status: job_status_counts.get(status, 0) for status in JobStatus
            },
        )

    async def trends(
        self,
        owner_id: UUID,
        *,
        weeks: int = DEFAULT_ANALYTICS_WEEKS,
        topics_per_week: int = DEFAULT_TOPICS_PER_WEEK,
    ) -> AnalyticsTrendsResponse:
        """Return UTC weekly decision, meeting-frequency, and topic trends."""
        _now, first_week_start, start, end = self._week_window(weeks)
        if (
            isinstance(topics_per_week, bool)
            or not 1 <= topics_per_week <= MAX_TOPICS_PER_WEEK
        ):
            raise ValueError("topics_per_week must be between 1 and 25.")
        values = await self._repository.get_trends(
            owner_id,
            week_start=start,
            week_end=end,
            topics_per_week=topics_per_week,
        )
        decision_counts = self._counts_by_week(values["decision_rows"])
        meeting_counts = self._counts_by_week(values["weekly_meeting_rows"])
        topic_counts: dict[date, list[TopicTrendCount]] = {
            first_week_start + timedelta(weeks=index): [] for index in range(weeks)
        }
        for row in values["topic_rows"]:
            week_start = self._as_date(row[0])
            if week_start in topic_counts:
                topic_counts[week_start].append(
                    TopicTrendCount(topic=row[1], count=row[2])
                )

        return AnalyticsTrendsResponse(
            decision_trends=[
                WeeklyDecisionCount(
                    week_start=week,
                    count=decision_counts.get(week, 0),
                )
                for week in topic_counts
            ],
            meeting_frequency=[
                WeeklyMeetingCount(
                    week_start=week,
                    count=meeting_counts.get(week, 0),
                )
                for week in topic_counts
            ],
            topic_trends=[
                WeeklyTopicTrend(week_start=week, topics=topics)
                for week, topics in topic_counts.items()
            ],
        )

    async def recurring_blockers(self, owner_id: UUID) -> RecurringBlockersResponse:
        """Return persisted blocker descriptions recurring across owned meetings."""
        rows = await self._repository.get_recurring_blockers(owner_id)
        blockers = []
        for row in rows:
            normalized = row["normalized_description"]
            evidence = [
                BlockerEvidenceReference(
                    meeting_id=meeting_id,
                    insight_id=insight_id,
                    title=title,
                    description=description,
                    insight_created_at=created_at,
                )
                for meeting_id, insight_id, title, description, created_at in row[
                    "evidence"
                ]
            ]
            if len({item.meeting_id for item in evidence}) < 2:
                # Defensive contract guard: never return a group without visible
                # provenance from two meetings, even if a repository regresses.
                continue
            blockers.append(
                RecurringBlocker(
                    group_id=hashlib.sha256(
                        f"blocker-description:v1:{normalized}".encode("utf-8")
                    ).hexdigest(),
                    description=evidence[0].description,
                    meeting_count=row["meeting_count"],
                    evidence_count=row["evidence_count"],
                    evidence_truncated=(
                        row["evidence_count"] > len(evidence)
                    ),
                    evidence=evidence,
                )
            )
        return RecurringBlockersResponse(recurring_blockers=blockers)

    async def task_completion_trends(
        self, owner_id: UUID
    ) -> TaskCompletionTrendsResponse:
        """Report why historical completion trends cannot be calculated."""
        # The owner is accepted to keep all analytics service calls uniformly
        # scoped; no database query can infer an event timestamp from updated_at.
        del owner_id
        return TaskCompletionTrendsResponse(
            available=False,
            reason=(
                "Historical completion trends are unavailable: persisted tasks "
                "have current status and updated_at only, with no completion "
                "timestamp or status-transition history."
            ),
        )

    async def speaker_participation(
        self,
        owner_id: UUID,
        *,
        meetings_limit: int = DEFAULT_SPEAKER_MEETING_LIMIT,
    ) -> SpeakerParticipationResponse:
        """Return bounded per-meeting counts of unique indexed transcript segments."""
        if (
            isinstance(meetings_limit, bool)
            or not 1 <= meetings_limit <= MAX_SPEAKER_MEETING_LIMIT
        ):
            raise ValueError("meetings_limit must be between 1 and 100.")
        values = await self._repository.get_speaker_participation(
            owner_id, meetings_limit=meetings_limit
        )
        meetings: dict[UUID, dict[str, object]] = {}
        for (
            meeting_id,
            transcript_id,
            segment_count,
            unknown_count,
            speaker_count,
            speaker,
            speaker_segments,
        ) in values["rows"]:
            current = meetings.setdefault(
                meeting_id,
                {
                    "meeting_id": meeting_id,
                    "transcript_id": transcript_id,
                    "segment_count": segment_count,
                    "unknown_speaker_segment_count": unknown_count,
                    "speaker_count": speaker_count,
                    "speakers": [],
                },
            )
            if speaker is not None and speaker_segments > 0:
                current["speakers"].append(
                    SpeakerCount(speaker=speaker, segment_count=speaker_segments)
                )
        results = [
            MeetingSpeakerParticipation(
                meeting_id=value["meeting_id"],
                transcript_id=value["transcript_id"],
                segment_count=value["segment_count"],
                unknown_speaker_segment_count=value[
                    "unknown_speaker_segment_count"
                ],
                speakers=value["speakers"],
                speakers_truncated=(
                    value["speaker_count"] > len(value["speakers"])
                ),
            )
            for value in meetings.values()
        ]
        total = values["total_transcripts"]
        return SpeakerParticipationResponse(
            total_transcripts=total,
            meetings=results,
            truncated=total > len(results),
        )

    def _week_window(
        self, weeks: int
    ) -> tuple[datetime, date, datetime, datetime]:
        if isinstance(weeks, bool) or not 1 <= weeks <= MAX_ANALYTICS_WEEKS:
            raise ValueError("weeks must be between 1 and 52.")
        now = self._clock()
        if now.utcoffset() is None:
            raise ValueError("Analytics clock must return a timezone-aware datetime.")
        now = now.astimezone(timezone.utc)
        current_week_start = now.date() - timedelta(days=now.weekday())
        first_week_start = current_week_start - timedelta(weeks=weeks - 1)
        start = datetime.combine(first_week_start, time.min, tzinfo=timezone.utc)
        end = datetime.combine(
            current_week_start + timedelta(weeks=1), time.min, tzinfo=timezone.utc
        )
        return now, first_week_start, start, end

    @staticmethod
    def _as_date(value: date | datetime) -> date:
        return value.date() if isinstance(value, datetime) else value

    @classmethod
    def _counts_by_week(cls, rows) -> dict[date, int]:
        return {cls._as_date(row[0]): row[1] for row in rows}


__all__ = ["AnalyticsService", "DEFAULT_ANALYTICS_WEEKS", "MAX_ANALYTICS_WEEKS"]
