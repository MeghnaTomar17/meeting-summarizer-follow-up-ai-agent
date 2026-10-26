"""Gateway evidence orchestration tests with deterministic service doubles."""

from __future__ import annotations

import importlib
import inspect
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

BACKEND_ROOT = Path(__file__).resolve().parents[1]
GATEWAY_ROOT = BACKEND_ROOT / "gateway-service"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _load_service():
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    for service_root in (str(GATEWAY_ROOT),):
        while service_root in sys.path:
            sys.path.remove(service_root)
    sys.path.insert(0, str(GATEWAY_ROOT))
    return importlib.import_module("app.services.cross_meeting_evidence").CrossMeetingEvidenceService


def _empty_structured():
    from shared.schemas.cross_meeting import CrossMeetingStructuredData
    from shared.schemas.pagination import build_paginated_response

    page = build_paginated_response([], page=1, page_size=20, total=0)
    return CrossMeetingStructuredData(meetings=page, tasks=page, decisions=page, insights=page)


def _bundle_fixtures():
    from shared.schemas.cross_meeting import (
        CrossMeetingDecisionRecord,
        CrossMeetingInsightRecord,
        CrossMeetingRecord,
        CrossMeetingStructuredData,
        CrossMeetingTaskRecord,
    )
    from shared.schemas.meeting_insight import InsightCategory
    from shared.schemas.pagination import build_paginated_response
    from shared.schemas.semantic_search import (
        SearchSourceSegment,
        SemanticSearchResponse,
        SemanticSearchResult,
    )
    from shared.schemas.task import TaskStatus

    now = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
    meeting_a, meeting_b = uuid.uuid4(), uuid.uuid4()
    transcript_id, chunk_id = uuid.uuid4(), uuid.uuid4()
    structured = CrossMeetingStructuredData(
        meetings=build_paginated_response(
            [CrossMeetingRecord(id=meeting_a, title="Atlas review", description="Atlas", scheduled_at=now, created_at=now)],
            page=1, page_size=3, total=1,
        ),
        tasks=build_paginated_response(
            [CrossMeetingTaskRecord(id=uuid.uuid4(), meeting_id=meeting_a, title="Review", description=None, status=TaskStatus.IN_PROGRESS, due_at=now, created_at=now)],
            page=1, page_size=3, total=1,
        ),
        decisions=build_paginated_response(
            [CrossMeetingDecisionRecord(id=uuid.uuid4(), meeting_id=meeting_b, statement="Proceed", context=None, participants=[], created_at=now)],
            page=1, page_size=3, total=1,
        ),
        insights=build_paginated_response(
            [CrossMeetingInsightRecord(id=uuid.uuid4(), meeting_id=meeting_b, category=InsightCategory.RISK, title="Delay", description="Review is late", created_at=now)],
            page=1, page_size=3, total=1,
        ),
    )
    semantic = SemanticSearchResponse(results=[SemanticSearchResult(
        meeting_id=meeting_b, transcript_id=transcript_id, chunk_id=chunk_id,
        chunk_index=2, text="The review is waiting on the vendor.", language="en",
        source_segments=[SearchSourceSegment(index=4, speaker="Ari", start_ms=120, end_ms=180)],
        start_ms=120, end_ms=180, score=0.87,
    )])
    return structured, semantic, (meeting_a, meeting_b, transcript_id, chunk_id)


class CrossMeetingEvidenceServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.Service = _load_service()
        self.owner_id = uuid.uuid4()
        self.request_id = "evidence-request-1"
        self.structured, self.semantic, self.ids = _bundle_fixtures()
        self.meeting_client = SimpleNamespace(
            query_cross_meeting_data=AsyncMock(return_value=self.structured)
        )
        self.search_client = SimpleNamespace(search=AsyncMock(return_value=self.semantic))
        self.service = self.Service(self.meeting_client, self.search_client)
        from shared.schemas.cross_meeting import (
            CrossMeetingDataQuery,
            CrossMeetingEvidenceRequest,
        )
        from shared.schemas.semantic_search import SemanticSearchRequest

        self.request = CrossMeetingEvidenceRequest(
            semantic=SemanticSearchRequest(query="What is blocking Atlas?", top_k=7),
            structured=CrossMeetingDataQuery(
                task_filter="unresolved", page=2, page_size=3,
                since=datetime(2026, 10, 1, tzinfo=timezone.utc),
            ),
        )

    async def test_composes_validated_sources_with_provenance_identity_bounds_and_request_id(self):
        result = await self.service.retrieve(
            self.request, user_id=self.owner_id, request_id=self.request_id
        )

        meeting_a, meeting_b, transcript_id, chunk_id = self.ids
        self.assertEqual(result.structured.meetings.items[0].id, meeting_a)
        self.assertEqual(result.structured.tasks.items[0].meeting_id, meeting_a)
        self.assertEqual(result.structured.decisions.items[0].meeting_id, meeting_b)
        self.assertEqual(result.structured.insights.items[0].meeting_id, meeting_b)
        chunk = result.semantic.results[0]
        self.assertEqual(chunk.meeting_id, meeting_b)
        self.assertEqual(chunk.transcript_id, transcript_id)
        self.assertEqual(chunk.chunk_id, chunk_id)
        self.assertEqual(chunk.source_segments[0].speaker, "Ari")
        self.assertEqual(chunk.source_segments[0].index, 4)
        self.assertEqual(chunk.score, 0.87)

        self.meeting_client.query_cross_meeting_data.assert_awaited_once_with(
            self.request.structured,
            user_id=self.owner_id,
            request_id=self.request_id,
        )
        self.search_client.search.assert_awaited_once_with(
            self.request.semantic,
            user_id=self.owner_id,
            request_id=self.request_id,
        )
        self.assertEqual(self.request.semantic.top_k, 7)
        self.assertEqual(self.request.structured.page_size, 3)

    async def test_structured_failure_is_sanitized_and_search_is_not_called(self):
        self.meeting_client.query_cross_meeting_data.side_effect = RuntimeError(
            "database-password=private"
        )
        from shared.exceptions.common import ServiceUnavailableError

        with self.assertRaises(ServiceUnavailableError) as raised:
            await self.service.retrieve(self.request, user_id=self.owner_id, request_id=None)
        self.assertNotIn("database-password", str(raised.exception))
        self.search_client.search.assert_not_awaited()

    async def test_semantic_failure_is_sanitized_without_returning_partial_structured_data(self):
        self.search_client.search.side_effect = RuntimeError("qdrant-key=private")
        from shared.exceptions.common import ServiceUnavailableError

        with self.assertRaises(ServiceUnavailableError) as raised:
            await self.service.retrieve(self.request, user_id=self.owner_id, request_id=None)
        self.assertNotIn("qdrant-key", str(raised.exception))
        self.meeting_client.query_cross_meeting_data.assert_awaited_once()

    async def test_malformed_downstream_contracts_are_rejected(self):
        from shared.exceptions.common import ServiceUnavailableError

        self.meeting_client.query_cross_meeting_data.return_value = {"meetings": []}
        with self.assertRaises(ServiceUnavailableError):
            await self.service.retrieve(self.request, user_id=self.owner_id, request_id=None)

        self.meeting_client.query_cross_meeting_data.return_value = self.structured
        self.search_client.search.return_value = {"results": [{"chunk_id": "invalid"}]}
        with self.assertRaises(ServiceUnavailableError):
            await self.service.retrieve(self.request, user_id=self.owner_id, request_id=None)

    async def test_empty_sources_are_preserved_as_empty_without_synthetic_evidence(self):
        from shared.schemas.semantic_search import SemanticSearchResponse

        self.meeting_client.query_cross_meeting_data.return_value = _empty_structured()
        self.search_client.search.return_value = self.semantic
        empty_structured_result = await self.service.retrieve(
            self.request, user_id=self.owner_id, request_id=None
        )
        self.assertEqual(empty_structured_result.structured.meetings.items, [])
        self.assertEqual(len(empty_structured_result.semantic.results), 1)

        self.meeting_client.query_cross_meeting_data.return_value = self.structured
        self.search_client.search.return_value = SemanticSearchResponse(results=[])
        empty_semantic_result = await self.service.retrieve(
            self.request, user_id=self.owner_id, request_id=None
        )
        self.assertEqual(len(empty_semantic_result.structured.meetings.items), 1)
        self.assertEqual(empty_semantic_result.semantic.results, [])

    async def test_question_reuses_both_retrieval_clients_then_ai_with_same_identity_and_request_id(self):
        from unittest.mock import AsyncMock
        from shared.schemas.cross_meeting import CrossMeetingQuestionRequest, CrossMeetingQuestionResponse
        ai_client = SimpleNamespace(answer=AsyncMock(return_value=CrossMeetingQuestionResponse(
            answer="Evidence supports the answer.", insufficient_evidence=False, citations=[]
        )))
        service = self.Service(self.meeting_client, self.search_client, ai_client)
        question = CrossMeetingQuestionRequest(
            question="What is blocking Atlas?", top_k=6,
            structured={"task_filter": "unresolved", "page_size": 5},
        )
        response = await service.answer(question, user_id=self.owner_id, request_id=self.request_id)
        self.assertEqual(response.answer, "Evidence supports the answer.")
        self.meeting_client.query_cross_meeting_data.assert_awaited_once_with(
            question.structured, user_id=self.owner_id, request_id=self.request_id
        )
        semantic_request = self.search_client.search.await_args.args[0]
        self.assertEqual(semantic_request.query, question.question)
        self.assertEqual(semantic_request.top_k, 6)
        ai_call = ai_client.answer.await_args
        self.assertEqual(ai_call.kwargs["user_id"], self.owner_id)
        self.assertEqual(ai_call.kwargs["request_id"], self.request_id)
        self.assertEqual(ai_call.args[0].evidence.semantic, self.semantic)

    async def test_this_month_derives_half_open_utc_window_and_scopes_vectors_to_month_meetings(self):
        from datetime import datetime, timezone
        from unittest.mock import AsyncMock
        from shared.schemas.cross_meeting import CrossMeetingQuestionRequest, CrossMeetingQuestionResponse
        from shared.schemas.semantic_search import SemanticSearchResponse
        fixed_now = datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc)
        matching_chunk = self.semantic.results[0].model_copy(
            update={"meeting_id": self.ids[0]}
        )
        self.search_client.search.return_value = SemanticSearchResponse(results=[matching_chunk])
        ai_client = SimpleNamespace(answer=AsyncMock(return_value=CrossMeetingQuestionResponse(
            answer="Possible recurring issue.", insufficient_evidence=True, citations=[]
        )))
        service = self.Service(
            self.meeting_client, self.search_client, ai_client, clock=lambda: fixed_now
        )
        question = CrossMeetingQuestionRequest(question="What recurring issues appeared this month?")
        await service.answer(question, user_id=self.owner_id, request_id=self.request_id)

        structured_query = self.meeting_client.query_cross_meeting_data.await_args.args[0]
        self.assertEqual(structured_query.since, datetime(2026, 12, 1, tzinfo=timezone.utc))
        self.assertEqual(structured_query.until, datetime(2027, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(structured_query.page, 1)
        self.assertEqual(structured_query.page_size, 100)
        semantic_query = self.search_client.search.await_args.args[0]
        self.assertEqual(semantic_query.meeting_ids, [self.ids[0]])
        self.assertEqual(semantic_query.query, question.question)

    async def test_overdue_and_unresolved_questions_select_database_semantics(self):
        from unittest.mock import AsyncMock
        from shared.schemas.cross_meeting import CrossMeetingQuestionRequest, CrossMeetingQuestionResponse
        ai_client = SimpleNamespace(answer=AsyncMock(return_value=CrossMeetingQuestionResponse(
            answer="Insufficient evidence.", insufficient_evidence=True, citations=[]
        )))
        service = self.Service(self.meeting_client, self.search_client, ai_client)
        for question_text, expected in (
            ("Which projects repeatedly missed deadlines?", "overdue"),
            ("Which action items are still unresolved?", "unresolved"),
        ):
            self.meeting_client.query_cross_meeting_data.reset_mock()
            ai_client.answer.reset_mock()
            await service.answer(
                CrossMeetingQuestionRequest(question=question_text),
                user_id=self.owner_id,
                request_id=self.request_id,
            )
            query = self.meeting_client.query_cross_meeting_data.await_args.args[0]
            self.assertEqual(query.task_filter.value, expected)
            self.assertEqual(ai_client.answer.await_args.args[0].task_filter.value, expected)

    def test_composed_request_reuses_existing_limits_and_rejects_owner_scope(self):
        from pydantic import ValidationError
        from shared.schemas.cross_meeting import CrossMeetingEvidenceRequest

        with self.assertRaises(ValidationError):
            CrossMeetingEvidenceRequest.model_validate({
                "semantic": {"query": "question", "top_k": 51},
                "structured": {},
            })
        with self.assertRaises(ValidationError):
            CrossMeetingEvidenceRequest.model_validate({
                "semantic": {"query": "question"},
                "structured": {"page_size": 101},
            })
        with self.assertRaises(ValidationError):
            CrossMeetingEvidenceRequest.model_validate({
                "semantic": {"query": "question"},
                "structured": {},
                "owner_id": str(uuid.uuid4()),
            })

    def test_orchestrator_does_not_depend_on_database_qdrant_or_llm_adapters(self):
        source = inspect.getsource(sys.modules[self.Service.__module__])
        for forbidden in (
            "AsyncSession", "create_async_engine", "QdrantVectorRepository",
            "AsyncQdrantClient", "AsyncOpenAI", "ModelProvider",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
