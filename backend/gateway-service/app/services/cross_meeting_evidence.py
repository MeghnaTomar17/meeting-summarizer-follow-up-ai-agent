"""Gateway orchestration for validated cross-meeting evidence retrieval."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from app.services.meeting_client import MeetingServiceClient
from app.services.search_client import SearchServiceClient
from app.services.ai_client import AIServiceClient
from shared.exceptions.common import ServiceUnavailableError
from shared.schemas.cross_meeting import (
    CrossMeetingEvidenceBundle,
    CrossMeetingEvidenceRequest,
    CrossMeetingAnswerGenerationRequest,
    CrossMeetingQuestionRequest,
    CrossMeetingQuestionResponse,
    CrossMeetingStructuredData,
)
from shared.schemas.semantic_search import SemanticSearchRequest, SemanticSearchResponse
from shared.api.constants import MAX_PAGE_SIZE
from shared.schemas.cross_meeting import StructuredTaskFilter

_logger = logging.getLogger(__name__)


class CrossMeetingEvidenceService:
    """Fetch each evidence source through its owning service boundary."""

    def __init__(
        self,
        meeting_client: MeetingServiceClient,
        search_client: SearchServiceClient,
        ai_client: AIServiceClient | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._meeting_client = meeting_client
        self._search_client = search_client
        self._ai_client = ai_client
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def retrieve(
        self,
        request: CrossMeetingEvidenceRequest,
        *,
        user_id: UUID,
        request_id: str | None,
        restrict_semantic_to_structured_meetings: bool = False,
    ) -> CrossMeetingEvidenceBundle:
        """Return a complete validated evidence bundle or a sanitized failure."""
        try:
            structured_response = await self._meeting_client.query_cross_meeting_data(
                request.structured,
                user_id=user_id,
                request_id=request_id,
            )
            structured = CrossMeetingStructuredData.model_validate(
                self._as_mapping(structured_response)
            )
        except Exception as error:
            _logger.error(
                "cross_meeting_structured_retrieval_failed error_type=%s",
                type(error).__name__,
            )
            raise ServiceUnavailableError(
                "Cross-meeting evidence is unavailable."
            ) from None

        semantic_request = request.semantic
        if restrict_semantic_to_structured_meetings:
            month_meeting_ids = [item.id for item in structured.meetings.items]
            semantic_request = semantic_request.model_copy(
                update={"meeting_ids": month_meeting_ids}
            )
        try:
            if semantic_request.meeting_ids == []:
                semantic = SemanticSearchResponse(results=[])
            else:
                semantic_response = await self._search_client.search(
                    semantic_request,
                    user_id=user_id,
                    request_id=request_id,
                )
                semantic = SemanticSearchResponse.model_validate(
                    self._as_mapping(semantic_response)
                )
            if semantic_request.meeting_ids is not None and any(
                result.meeting_id not in set(semantic_request.meeting_ids)
                for result in semantic.results
            ):
                raise ValueError("Search returned results outside the meeting filter.")
        except Exception as error:
            _logger.error(
                "cross_meeting_semantic_retrieval_failed error_type=%s",
                type(error).__name__,
            )
            raise ServiceUnavailableError(
                "Cross-meeting evidence is unavailable."
            ) from None

        return CrossMeetingEvidenceBundle(structured=structured, semantic=semantic)

    async def answer(
        self,
        request: CrossMeetingQuestionRequest,
        *,
        user_id: UUID,
        request_id: str | None,
    ) -> CrossMeetingQuestionResponse:
        """Retrieve through Block 2, then delegate answer generation to AI Service."""
        if self._ai_client is None:
            raise ServiceUnavailableError("The answer service is unavailable.")
        question = request.question.casefold()
        calendar_month = "this month" in question or "current month" in question
        task_filter = request.structured.task_filter
        if ("missed" in question and "deadline" in question) or "overdue" in question or "past due" in question:
            task_filter = StructuredTaskFilter.OVERDUE
        elif "unresolved" in question and ("task" in question or "action item" in question):
            task_filter = StructuredTaskFilter.UNRESOLVED

        structured_query = request.structured.model_copy(update={"task_filter": task_filter})
        if calendar_month:
            now = self._clock()
            if now.utcoffset() is None:
                raise ValueError("Gateway clock must return a timezone-aware datetime.")
            now = now.astimezone(timezone.utc)
            month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
            if now.month == 12:
                month_end = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
            else:
                month_end = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
            since = max(filter(None, (structured_query.since, month_start)))
            until = min(filter(None, (structured_query.until, month_end)))
            if since >= until:
                return CrossMeetingQuestionResponse(
                    answer="The requested time window contains no dates in the current calendar month.",
                    insufficient_evidence=True,
                    citations=[],
                )
            structured_query = structured_query.model_copy(update={
                "since": since, "until": until, "page": 1,
                "page_size": MAX_PAGE_SIZE,
            })
        retrieval = CrossMeetingEvidenceRequest(
            semantic=SemanticSearchRequest(query=request.question, top_k=request.top_k),
            structured=structured_query,
        )
        evidence = await self.retrieve(
            retrieval, user_id=user_id, request_id=request_id,
            restrict_semantic_to_structured_meetings=calendar_month,
        )
        try:
            return await self._ai_client.answer(
                CrossMeetingAnswerGenerationRequest(
                    question=request.question, evidence=evidence,
                    task_filter=structured_query.task_filter,
                ),
                user_id=user_id,
                request_id=request_id,
            )
        except Exception as error:
            _logger.error("cross_meeting_answer_generation_failed error_type=%s", type(error).__name__)
            raise ServiceUnavailableError("The answer service is unavailable.") from None

    @staticmethod
    def _as_mapping(value: object) -> object:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="python")
        return value


__all__ = ["CrossMeetingEvidenceService"]
