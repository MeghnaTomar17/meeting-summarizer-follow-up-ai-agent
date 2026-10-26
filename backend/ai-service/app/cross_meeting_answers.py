"""AI-owned cross-meeting generation and citation validation."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from agents.cross_meeting_agent import CrossMeetingAnswerAgent, CrossMeetingAnswerOutput
from llm.errors import ModelExecutionError
from llm.provider import ModelProvider
from llm.structured_output import generate_structured_output
from shared.schemas.cross_meeting import (
    CrossMeetingAnswerGenerationRequest,
    CrossMeetingCitation,
    CrossMeetingCitationType,
    CrossMeetingQuestionResponse,
    StructuredTaskFilter,
)


class CrossMeetingAnswerService:
    def __init__(self, provider: ModelProvider) -> None:
        self._provider = provider

    async def answer(self, request: CrossMeetingAnswerGenerationRequest) -> CrossMeetingQuestionResponse:
        evidence = request.evidence
        evidence_by_id: dict[str, CrossMeetingCitation] = {}
        structured = evidence.structured
        pages = (
            ("meetings", CrossMeetingCitationType.MEETING, "scheduled_at"),
            ("tasks", CrossMeetingCitationType.TASK, "created_at"),
            ("decisions", CrossMeetingCitationType.DECISION, "created_at"),
            ("insights", CrossMeetingCitationType.INSIGHT, "created_at"),
        )
        for field, source_type, timestamp_field in pages:
            for record in getattr(structured, field).items:
                citation = CrossMeetingCitation(
                    source_type=source_type,
                    record_id=record.id,
                    meeting_id=record.id if field == "meetings" else record.meeting_id,
                    timestamp=getattr(record, timestamp_field),
                    due_at=getattr(record, "due_at", None),
                    status=getattr(record, "status", None),
                )
                evidence_by_id[str(record.id)] = citation
        for chunk in evidence.semantic.results:
            evidence_by_id[str(chunk.chunk_id)] = CrossMeetingCitation(
                source_type=CrossMeetingCitationType.TRANSCRIPT_CHUNK,
                record_id=chunk.chunk_id,
                meeting_id=chunk.meeting_id,
                transcript_id=chunk.transcript_id,
                start_ms=chunk.start_ms,
                end_ms=chunk.end_ms,
            )

        if not evidence_by_id:
            return CrossMeetingQuestionResponse(
                answer="I do not have enough retrieved evidence to answer this question.",
                insufficient_evidence=True,
                citations=[],
            )

        trusted_now = datetime.now(timezone.utc)
        question_text = request.question.casefold()
        task_question = any(word in question_text for word in ("task", "action item", "deadline"))
        unresolved_question = task_question and any(
            word in question_text for word in ("unresolved", "still open", "remain open", "open task", "open action")
        )
        overdue_question = task_question and (
            "overdue" in question_text
            or "past due" in question_text
            or ("missed" in question_text and "deadline" in question_text)
        )
        recurrence_question = any(
            phrase in question_text
            for phrase in ("recurring", "repeated issue", "repeated problem", "across meetings", "again and again")
        )
        decision_question = any(
            term in question_text for term in ("decision", "decisions", "decide")
        )
        decision_evidence_ids = {
            identifier for identifier, citation in evidence_by_id.items()
            if citation.source_type in {
                CrossMeetingCitationType.DECISION,
                CrossMeetingCitationType.TRANSCRIPT_CHUNK,
            }
        }
        if decision_question and not decision_evidence_ids:
            return CrossMeetingQuestionResponse(
                answer="I do not have retrieved decision or transcript evidence to answer this question.",
                insufficient_evidence=True,
                citations=[],
            )
        tasks = structured.tasks.items
        if unresolved_question and not any(task.status.value in {"open", "in_progress"} for task in tasks):
            return CrossMeetingQuestionResponse(
                answer="No unresolved tasks are present in the retrieved structured evidence.",
                insufficient_evidence=True,
                citations=[],
            )
        eligible_overdue = (
            list(tasks)
            if request.task_filter == StructuredTaskFilter.OVERDUE
            else [
                task for task in tasks
                if task.due_at is not None and task.due_at < trusted_now
                and task.status.value not in {"done", "cancelled"}
            ]
        )
        if overdue_question and request.task_filter == StructuredTaskFilter.OVERDUE and not tasks:
            return CrossMeetingQuestionResponse(
                answer="The retrieved structured evidence does not establish an overdue task.",
                insufficient_evidence=True,
                citations=[],
            )
        if overdue_question and tasks and not eligible_overdue:
            return CrossMeetingQuestionResponse(
                answer="The retrieved structured evidence does not establish an overdue task.",
                insufficient_evidence=True,
                citations=[],
            )

        model_request = CrossMeetingAnswerAgent.build_question_request(
            request.question,
            evidence,
            now=trusted_now.isoformat(),
            task_filter=request.task_filter.value,
        )
        try:
            generated = await generate_structured_output(
                self._provider, model_request, CrossMeetingAnswerOutput
            )
        except ModelExecutionError:
            raise
        except Exception:
            from llm.errors import MalformedModelOutputError
            raise MalformedModelOutputError() from None

        if len(set(generated.evidence_ids)) != len(generated.evidence_ids):
            from llm.errors import MalformedModelOutputError
            raise MalformedModelOutputError() from None
        if generated.insufficient_evidence and not generated.answer.strip():
            from llm.errors import MalformedModelOutputError
            raise MalformedModelOutputError() from None
        try:
            citations = [evidence_by_id[item] for item in generated.evidence_ids]
        except KeyError:
            from llm.errors import MalformedModelOutputError
            raise MalformedModelOutputError() from None
        if not generated.insufficient_evidence and not citations:
            from llm.errors import MalformedModelOutputError
            raise MalformedModelOutputError() from None

        cited_ids = {str(citation.record_id) for citation in citations}
        task_ids = {str(task.id) for task in tasks}
        eligible_unresolved_ids = {
            str(task.id) for task in tasks if task.status.value in {"open", "in_progress"}
        }
        eligible_overdue_ids = {str(task.id) for task in eligible_overdue}
        if unresolved_question and cited_ids & (task_ids - eligible_unresolved_ids):
            from llm.errors import MalformedModelOutputError
            raise MalformedModelOutputError() from None
        if unresolved_question and tasks and not generated.insufficient_evidence and not (cited_ids & eligible_unresolved_ids):
            from llm.errors import MalformedModelOutputError
            raise MalformedModelOutputError() from None
        if overdue_question and cited_ids & (task_ids - eligible_overdue_ids):
            from llm.errors import MalformedModelOutputError
            raise MalformedModelOutputError() from None
        if overdue_question and tasks and not generated.insufficient_evidence and not (cited_ids & eligible_overdue_ids):
            from llm.errors import MalformedModelOutputError
            raise MalformedModelOutputError() from None
        if decision_question and not generated.insufficient_evidence and not (cited_ids & decision_evidence_ids):
            from llm.errors import MalformedModelOutputError
            raise MalformedModelOutputError() from None

        # A recurrence claim needs actual support across distinct meetings.
        recurrence_words = ("recurring", "repeated", "keeps happening", "repeatedly")
        if recurrence_question or any(word in generated.answer.casefold() for word in recurrence_words):
            cited_meetings = {citation.meeting_id for citation in citations}
            if len(cited_meetings) < 2:
                return CrossMeetingQuestionResponse(
                    answer="The retrieved evidence does not establish a recurring issue across distinct meetings.",
                    insufficient_evidence=True,
                    citations=citations,
                )

        repeated_deadline_question = overdue_question and any(
            word in question_text for word in ("repeat", "repeated", "repeatedly", "recurring")
        )
        if repeated_deadline_question and not generated.insufficient_evidence:
            cited_overdue_meetings = {
                str(task.meeting_id)
                for task in tasks
                if str(task.id) in cited_ids and str(task.id) in eligible_overdue_ids
            }
            if len(cited_overdue_meetings) < 2:
                return CrossMeetingQuestionResponse(
                    answer="The retrieved evidence does not establish repeated deadline problems across distinct meetings.",
                    insufficient_evidence=True,
                    citations=citations,
                )

        return CrossMeetingQuestionResponse(
            answer=generated.answer.strip(),
            insufficient_evidence=generated.insufficient_evidence,
            citations=citations,
        )


__all__ = ["CrossMeetingAnswerService"]
