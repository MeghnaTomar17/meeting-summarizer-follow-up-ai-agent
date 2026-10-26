"""PostgreSQL aggregate queries for owner-scoped dashboard analytics."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import case, cast, func, literal, select, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.models.decision import Decision
from shared.database.models.followup import Followup
from shared.database.models.meeting import Meeting
from shared.database.models.processing_job import ProcessingJobRecord
from shared.database.models.summary import Summary
from shared.database.models.task import Task, TaskStatus
from shared.database.models.transcript import Transcript
from shared.jobs.lifecycle import JobStatus
from shared.schemas.followup import FollowupStatus
from shared.schemas.meeting import MeetingStatus
from shared.schemas.meeting_insight import InsightCategory
from shared.database.models.meeting_insight import MeetingInsight
from shared.schemas.analytics import (
    MAX_BLOCKER_EVIDENCE_PER_GROUP,
    MAX_SPEAKERS_PER_MEETING,
    MAX_RECURRING_BLOCKERS,
)


class AnalyticsRepository:
    """Run bounded aggregate queries without loading domain rows into Python."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_overview(
        self,
        owner_id: UUID,
        *,
        week_start: datetime,
        week_end: datetime,
        as_of: datetime,
    ) -> dict[str, object]:
        """Return aggregate values scoped through the owner's meetings."""
        total_meetings = await self._scalar(
            select(func.count(Meeting.id)).where(Meeting.created_by == owner_id)
        )

        weekly_rows = await self._weekly_meeting_rows(
            owner_id, week_start=week_start, week_end=week_end
        )

        task_statement = (
            select(Task.status, func.count(Task.id))
            .join(Meeting, Task.meeting_id == Meeting.id)
            .where(Meeting.created_by == owner_id)
            .group_by(Task.status)
        )
        task_result = await self._session.execute(task_statement)
        task_counts = {TaskStatus(status): int(count) for status, count in task_result.all()}

        overdue_count = await self._scalar(
            select(func.count(Task.id))
            .join(Meeting, Task.meeting_id == Meeting.id)
            .where(
                Meeting.created_by == owner_id,
                Task.due_at.is_not(None),
                Task.due_at < as_of,
                Task.status.notin_((TaskStatus.DONE, TaskStatus.CANCELLED)),
            )
        )
        decision_count = await self._scalar(
            select(func.count(Decision.id))
            .join(Meeting, Decision.meeting_id == Meeting.id)
            .where(Meeting.created_by == owner_id)
        )

        followup_statement = (
            select(Followup.status, func.count(Followup.id))
            .join(Meeting, Followup.meeting_id == Meeting.id)
            .where(Meeting.created_by == owner_id)
            .group_by(Followup.status)
        )
        followup_result = await self._session.execute(followup_statement)
        followup_counts = {
            FollowupStatus(status): int(count)
            for status, count in followup_result.all()
        }

        meeting_status_statement = (
            select(Meeting.status, func.count(Meeting.id))
            .where(Meeting.created_by == owner_id)
            .group_by(Meeting.status)
        )
        meeting_status_result = await self._session.execute(meeting_status_statement)
        meeting_status_counts = {
            MeetingStatus(status): int(count)
            for status, count in meeting_status_result.all()
        }

        job_status_statement = (
            select(ProcessingJobRecord.status, func.count(ProcessingJobRecord.job_id))
            .join(Meeting, ProcessingJobRecord.meeting_id == Meeting.id)
            .where(
                Meeting.created_by == owner_id,
                ProcessingJobRecord.owner_id == owner_id,
            )
            .group_by(ProcessingJobRecord.status)
        )
        job_status_result = await self._session.execute(job_status_statement)
        job_status_counts = {
            JobStatus(status): int(count) for status, count in job_status_result.all()
        }

        return {
            "total_meetings": total_meetings,
            "weekly_rows": weekly_rows,
            "task_counts": task_counts,
            "overdue_tasks": overdue_count,
            "decisions": decision_count,
            "followup_counts": followup_counts,
            "meeting_status_counts": meeting_status_counts,
            "processing_job_status_counts": job_status_counts,
        }

    async def get_trends(
        self,
        owner_id: UUID,
        *,
        week_start: datetime,
        week_end: datetime,
        topics_per_week: int,
    ) -> dict[str, object]:
        """Aggregate weekly decisions, scheduled meetings, and latest topics."""
        weekly_meetings = await self._weekly_meeting_rows(
            owner_id, week_start=week_start, week_end=week_end
        )
        decision_week = func.date_trunc(
            "week", func.timezone("UTC", Decision.created_at)
        )
        decision_statement = (
            select(decision_week.label("week_start"), func.count(Decision.id))
            .join(Meeting, Decision.meeting_id == Meeting.id)
            .where(
                Meeting.created_by == owner_id,
                Decision.created_at >= week_start,
                Decision.created_at < week_end,
            )
            .group_by(decision_week)
            .order_by(decision_week)
        )
        decision_result = await self._session.execute(decision_statement)
        decision_rows = [(row[0], int(row[1])) for row in decision_result.all()]

        topic_rows = await self._topic_rows(
            owner_id,
            week_start=week_start,
            week_end=week_end,
            topics_per_week=topics_per_week,
        )
        return {
            "weekly_meeting_rows": weekly_meetings,
            "decision_rows": decision_rows,
            "topic_rows": topic_rows,
        }

    async def get_recurring_blockers(self, owner_id: UUID) -> list[dict[str, object]]:
        """Return exact normalized blocker-description groups with bounded evidence.

        A group qualifies only when its normalized description occurs on at least
        two distinct meetings owned by ``owner_id``. Semantic similarity is not
        inferred. Evidence ordering prefers one row per meeting before duplicates.
        """
        normalized = func.btrim(
            func.regexp_replace(
                func.lower(MeetingInsight.description), r"\s+", " ", "g"
            )
        )
        base = (
            select(
                normalized.label("normalized_description"),
                MeetingInsight.id.label("insight_id"),
                MeetingInsight.meeting_id.label("meeting_id"),
                MeetingInsight.title.label("title"),
                MeetingInsight.description.label("description"),
                MeetingInsight.created_at.label("insight_created_at"),
            )
            .join(Meeting, Meeting.id == MeetingInsight.meeting_id)
            .where(
                Meeting.created_by == owner_id,
                MeetingInsight.category == InsightCategory.BLOCKER,
                normalized != "",
            )
            .cte("owned_blocker_insights")
        )
        grouped = (
            select(
                base.c.normalized_description,
                func.count(func.distinct(base.c.meeting_id)).label("meeting_count"),
                func.count(base.c.insight_id).label("evidence_count"),
            )
            .group_by(base.c.normalized_description)
            .having(func.count(func.distinct(base.c.meeting_id)) >= 2)
            .order_by(
                func.count(func.distinct(base.c.meeting_id)).desc(),
                base.c.normalized_description.asc(),
            )
            .limit(MAX_RECURRING_BLOCKERS)
            .cte("recurring_blocker_groups")
        )
        group_result = await self._session.execute(
            select(
                grouped.c.normalized_description,
                grouped.c.meeting_count,
                grouped.c.evidence_count,
            ).order_by(grouped.c.meeting_count.desc(), grouped.c.normalized_description)
        )
        groups = [tuple(row) for row in group_result.all()]
        if not groups:
            return []

        descriptions = [row[0] for row in groups]
        evidence_base = (
            select(
                base.c.normalized_description,
                base.c.meeting_id,
                base.c.insight_id,
                base.c.title,
                base.c.description,
                base.c.insight_created_at,
                func.row_number()
                .over(
                    partition_by=(base.c.normalized_description, base.c.meeting_id),
                    order_by=(base.c.insight_created_at.asc(), base.c.insight_id.asc()),
                )
                .label("meeting_evidence_rank"),
            )
            .where(base.c.normalized_description.in_(descriptions))
            .subquery("ranked_blocker_evidence_per_meeting")
        )
        ranked_evidence = (
            select(
                evidence_base.c.normalized_description,
                evidence_base.c.meeting_id,
                evidence_base.c.insight_id,
                evidence_base.c.title,
                evidence_base.c.description,
                evidence_base.c.insight_created_at,
                func.row_number()
                .over(
                    partition_by=evidence_base.c.normalized_description,
                    order_by=(
                        evidence_base.c.meeting_evidence_rank.asc(),
                        evidence_base.c.meeting_id.asc(),
                        evidence_base.c.insight_created_at.asc(),
                        evidence_base.c.insight_id.asc(),
                    ),
                )
                .label("evidence_rank"),
            )
            .subquery("ranked_blocker_evidence")
        )
        evidence_result = await self._session.execute(
            select(
                ranked_evidence.c.normalized_description,
                ranked_evidence.c.meeting_id,
                ranked_evidence.c.insight_id,
                ranked_evidence.c.title,
                ranked_evidence.c.description,
                ranked_evidence.c.insight_created_at,
            )
            .where(ranked_evidence.c.evidence_rank <= MAX_BLOCKER_EVIDENCE_PER_GROUP)
            .order_by(
                ranked_evidence.c.normalized_description,
                ranked_evidence.c.evidence_rank,
            )
        )
        evidence_rows: dict[str, list[tuple[object, ...]]] = {
            str(description): [] for description in descriptions
        }
        for row in evidence_result.all():
            evidence_rows[str(row[0])].append(tuple(row[1:]))
        return [
            {
                "normalized_description": str(description),
                "meeting_count": int(meeting_count),
                "evidence_count": int(evidence_count),
                "evidence": evidence_rows[str(description)],
            }
            for description, meeting_count, evidence_count in groups
        ]

    async def get_speaker_participation(
        self, owner_id: UUID, *, meetings_limit: int
    ) -> dict[str, object]:
        """Count unique indexed transcript segments by meeting-local speaker label.

        Transcript segments are expanded and aggregated in PostgreSQL, so text
        is never returned to the application result. Duplicate segment indexes
        within one transcript are counted once (first JSON array occurrence).
        """
        owner_transcripts = (
            select(
                Meeting.id.label("meeting_id"),
                Meeting.created_at.label("meeting_created_at"),
                Transcript.id.label("transcript_id"),
                Transcript.segments.label("segments"),
                func.count(Transcript.id).over().label("total_transcripts"),
            )
            .join(Transcript, Transcript.meeting_id == Meeting.id)
            .where(Meeting.created_by == owner_id)
            .order_by(Meeting.created_at.desc(), Meeting.id.asc())
            .limit(meetings_limit)
            .cte("recent_owned_transcripts")
        )
        safe_segments = case(
            (
                func.jsonb_typeof(owner_transcripts.c.segments) == "array",
                owner_transcripts.c.segments,
            ),
            else_=cast(literal("[]"), JSONB),
        )
        segment_elements = func.jsonb_array_elements(
            safe_segments
        ).table_valued("value", with_ordinality="ordinality").lateral(
            "speaker_segment_elements"
        )
        raw_index = segment_elements.c.value.op("->>")(literal("index"))
        valid_index = raw_index.op("~")(literal(r"^[0-9]+$"))
        raw_speaker = segment_elements.c.value.op("->>")(literal("speaker"))
        trimmed_speaker = func.btrim(raw_speaker)
        normalized_speaker = case(
            (
                func.lower(trimmed_speaker).in_(("", "unknown")),
                None,
            ),
            else_=func.lower(trimmed_speaker),
        )
        display_speaker = case(
            (normalized_speaker.is_(None), None),
            else_=trimmed_speaker,
        )
        ranked_segments = (
            select(
                owner_transcripts.c.meeting_id,
                owner_transcripts.c.meeting_created_at,
                owner_transcripts.c.transcript_id,
                owner_transcripts.c.total_transcripts,
                raw_index.label("segment_index"),
                normalized_speaker.label("normalized_speaker"),
                display_speaker.label("display_speaker"),
                func.row_number()
                .over(
                    partition_by=(
                        owner_transcripts.c.transcript_id,
                        raw_index,
                    ),
                    order_by=segment_elements.c.ordinality.asc(),
                )
                .label("duplicate_rank"),
            )
            .select_from(
                owner_transcripts.outerjoin(segment_elements, valid_index)
            )
            .subquery("ranked_transcript_segments")
        )
        speaker_groups = (
            select(
                ranked_segments.c.meeting_id,
                ranked_segments.c.meeting_created_at,
                ranked_segments.c.transcript_id,
                ranked_segments.c.total_transcripts,
                ranked_segments.c.normalized_speaker,
                func.min(ranked_segments.c.display_speaker).label("speaker"),
                func.count(ranked_segments.c.segment_index).label("speaker_segments"),
            )
            .where(ranked_segments.c.duplicate_rank == 1)
            .group_by(
                ranked_segments.c.meeting_id,
                ranked_segments.c.meeting_created_at,
                ranked_segments.c.transcript_id,
                ranked_segments.c.total_transcripts,
                ranked_segments.c.normalized_speaker,
            )
            .subquery("speaker_segment_counts")
        )
        ranked_speakers = (
            select(
                speaker_groups.c.meeting_id,
                speaker_groups.c.meeting_created_at,
                speaker_groups.c.transcript_id,
                speaker_groups.c.total_transcripts,
                func.sum(speaker_groups.c.speaker_segments)
                .over(partition_by=speaker_groups.c.meeting_id)
                .label("segment_count"),
                func.sum(
                    case(
                        (
                            speaker_groups.c.normalized_speaker.is_(None),
                            speaker_groups.c.speaker_segments,
                        ),
                        else_=0,
                    )
                )
                .over(partition_by=speaker_groups.c.meeting_id)
                .label("unknown_segment_count"),
                func.sum(
                    case(
                        (speaker_groups.c.normalized_speaker.is_not(None), 1),
                        else_=0,
                    )
                )
                .over(partition_by=speaker_groups.c.meeting_id)
                .label("speaker_count"),
                speaker_groups.c.speaker,
                speaker_groups.c.normalized_speaker,
                speaker_groups.c.speaker_segments,
                func.row_number()
                .over(
                    partition_by=speaker_groups.c.meeting_id,
                    order_by=(
                        speaker_groups.c.speaker_segments.desc(),
                        speaker_groups.c.normalized_speaker.asc().nulls_last(),
                    ),
                )
                .label("speaker_rank"),
            )
            .subquery("ranked_speaker_counts")
        )
        statement = (
            select(
                ranked_speakers.c.total_transcripts,
                ranked_speakers.c.meeting_id,
                ranked_speakers.c.transcript_id,
                ranked_speakers.c.segment_count,
                ranked_speakers.c.unknown_segment_count,
                ranked_speakers.c.speaker_count,
                ranked_speakers.c.speaker,
                ranked_speakers.c.speaker_segments,
            )
            .where(
                ranked_speakers.c.normalized_speaker.is_(None)
                | (ranked_speakers.c.speaker_rank <= MAX_SPEAKERS_PER_MEETING)
            )
            .order_by(
                ranked_speakers.c.meeting_created_at.desc(),
                ranked_speakers.c.meeting_id.asc(),
                ranked_speakers.c.speaker_rank.asc(),
            )
        )
        result = await self._session.execute(statement)
        rows = [tuple(row) for row in result.all()]
        return {
            "total_transcripts": int(rows[0][0]) if rows else 0,
            "rows": [row[1:] for row in rows],
        }

    async def _weekly_meeting_rows(
        self, owner_id: UUID, *, week_start: datetime, week_end: datetime
    ) -> list[tuple[datetime, int]]:
        """Share the Block 1 UTC scheduled-meeting aggregation exactly."""
        week_bucket = func.date_trunc(
            "week", func.timezone("UTC", Meeting.scheduled_at)
        )
        statement = (
            select(week_bucket.label("week_start"), func.count(Meeting.id))
            .where(
                Meeting.created_by == owner_id,
                Meeting.scheduled_at >= week_start,
                Meeting.scheduled_at < week_end,
            )
            .group_by(week_bucket)
            .order_by(week_bucket)
        )
        result = await self._session.execute(statement)
        return [(row[0], int(row[1])) for row in result.all()]

    async def _topic_rows(
        self,
        owner_id: UUID,
        *,
        week_start: datetime,
        week_end: datetime,
        topics_per_week: int,
    ) -> list[tuple[datetime, str, int]]:
        """Count distinct normalized topics from latest summaries per meeting.

        JSONB values that are not arrays, and array elements that are not
        strings, are ignored. Duplicate normalized strings count once per
        meeting. Topics longer than the public contract limit are excluded.
        """
        summary_rank = func.row_number().over(
            partition_by=Summary.meeting_id,
            order_by=(Summary.version.desc(), Summary.created_at.desc()),
        ).label("summary_rank")
        ranked_summaries = (
            select(
                Summary.meeting_id,
                Summary.key_topics,
                summary_rank,
            )
            .join(Meeting, Summary.meeting_id == Meeting.id)
            .where(Meeting.created_by == owner_id)
            .subquery("ranked_owner_summaries")
        )
        week_bucket = func.date_trunc(
            "week", func.timezone("UTC", Meeting.scheduled_at)
        )
        topic_source = (
            select(
                Meeting.id.label("meeting_id"),
                week_bucket.label("week_start"),
                ranked_summaries.c.key_topics,
            )
            .join(ranked_summaries, ranked_summaries.c.meeting_id == Meeting.id)
            .where(
                Meeting.created_by == owner_id,
                Meeting.scheduled_at >= week_start,
                Meeting.scheduled_at < week_end,
                ranked_summaries.c.summary_rank == 1,
            )
            .cte("owner_meeting_topics")
        )
        safe_topics = case(
            (func.jsonb_typeof(topic_source.c.key_topics) == "array", topic_source.c.key_topics),
            else_=cast(literal("[]"), JSONB),
        )
        topic_elements = func.jsonb_array_elements(safe_topics).table_valued(
            "value"
        ).lateral("topic_elements")
        raw_topic = topic_elements.c.value.op("#>>")(literal("{}"))
        normalized_topic = func.btrim(
            func.regexp_replace(func.lower(raw_topic), r"\s+", " ", "g")
        )
        distinct_topics = (
            select(
                topic_source.c.meeting_id,
                topic_source.c.week_start,
                normalized_topic.label("topic"),
            )
            .select_from(topic_source.join(topic_elements, true()))
            .where(
                func.jsonb_typeof(topic_elements.c.value) == "string",
                normalized_topic != "",
                func.length(normalized_topic) <= 500,
            )
            .distinct()
            .cte("distinct_meeting_topics")
        )
        topic_counts = (
            select(
                distinct_topics.c.week_start,
                distinct_topics.c.topic,
                func.count(distinct_topics.c.meeting_id).label("count"),
            )
            .group_by(distinct_topics.c.week_start, distinct_topics.c.topic)
            .cte("topic_counts")
        )
        ranked_topics = (
            select(
                topic_counts.c.week_start,
                topic_counts.c.topic,
                topic_counts.c.count,
                func.row_number()
                .over(
                    partition_by=topic_counts.c.week_start,
                    order_by=(topic_counts.c.count.desc(), topic_counts.c.topic.asc()),
                )
                .label("topic_rank"),
            )
            .subquery("ranked_weekly_topics")
        )
        statement = (
            select(
                ranked_topics.c.week_start,
                ranked_topics.c.topic,
                ranked_topics.c.count,
            )
            .where(ranked_topics.c.topic_rank <= topics_per_week)
            .order_by(ranked_topics.c.week_start, ranked_topics.c.topic_rank)
        )
        result = await self._session.execute(statement)
        return [(row[0], str(row[1]), int(row[2])) for row in result.all()]

    async def _scalar(self, statement) -> int:
        result = await self._session.execute(statement)
        value = result.scalar_one()
        return int(value or 0)


__all__ = ["AnalyticsRepository"]
