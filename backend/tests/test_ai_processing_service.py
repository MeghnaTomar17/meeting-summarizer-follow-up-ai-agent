"""Unit tests for the AI application processing boundary."""

from __future__ import annotations

import asyncio
import ast
import importlib
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

BACKEND_ROOT = Path(__file__).resolve().parents[1]
AI_SERVICE_ROOT = BACKEND_ROOT / "ai-service"
MEETING_ID = UUID("d146f98d-d557-4b89-a746-3e48e73d46b1")
TRANSCRIPT_ID = UUID("084c3a14-1a7f-41c9-a7c8-1e195aa5313a")


def _prepare_imports() -> None:
    for module_name in list(sys.modules):
        if any(
            module_name == package or module_name.startswith(f"{package}.")
            for package in ("app", "agents", "llm")
        ):
            del sys.modules[module_name]
    for service in ("gateway-service", "meeting-service", "ai-service"):
        root = str(BACKEND_ROOT / service)
        while root in sys.path:
            sys.path.remove(root)
    sys.path.insert(0, str(BACKEND_ROOT))
    sys.path.insert(0, str(AI_SERVICE_ROOT))


class AIProcessingServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        _prepare_imports()
        self.contracts = importlib.import_module("app.contracts")
        self.results = importlib.import_module("app.processing_results")
        self.domain_mapping = importlib.import_module("app.domain_mapping")
        self.transcript_mapping = importlib.import_module("app.transcript_mapping")
        self.processing_module = importlib.import_module("app.processing_service")
        self.summary_agent = importlib.import_module("agents.summary_agent")
        self.task_agent = importlib.import_module("agents.task_agent")
        self.decision_agent = importlib.import_module("agents.decision_agent")
        self.followup_agent = importlib.import_module("agents.followup_agent")
        self.insight_agent = importlib.import_module("agents.insight_agent")
        self.transcript_schema = importlib.import_module("shared.schemas.transcript")
        self.orchestrator = MagicMock()
        self.orchestrator.process = AsyncMock()
        self.service = self.processing_module.AIProcessingService(
            self.orchestrator
        )

    def _request(self, operations=None, *, context=None):
        if operations is None:
            operations = [self.contracts.ProcessingOperation.SUMMARY]
        return self.contracts.ProcessingRequest(
            meeting_id=MEETING_ID,
            transcript_id=TRANSCRIPT_ID,
            requested_operations=operations,
            context=context,
        )

    def _transcript(self, *, meeting_id=MEETING_ID, transcript_id=TRANSCRIPT_ID):
        now = datetime(2026, 10, 2, tzinfo=timezone.utc)
        return self.transcript_schema.TranscriptInDB(
            id=str(transcript_id),
            meeting_id=str(meeting_id),
            language="en",
            segments=[
                self.transcript_schema.TranscriptSegment(
                    index=0, speaker="Ravi", text="We will send the launch plan."
                )
            ],
            created_at=now,
            updated_at=now,
        )

    def _output(self, operation):
        O = self.contracts.ProcessingOperation
        if operation == O.SUMMARY:
            return self.summary_agent.SummaryAgentOutput(
                content="The launch plan is ready.", key_topics=["launch"]
            )
        if operation == O.TASKS:
            return self.task_agent.TaskAgentOutput(
                tasks=[self.task_agent.TaskCandidate(title="Send launch plan")]
            )
        if operation == O.DECISIONS:
            return self.decision_agent.DecisionAgentOutput(
                decisions=[
                    self.decision_agent.DecisionCandidate(
                        statement="Use the revised launch plan", participants=["Ravi"]
                    )
                ]
            )
        if operation == O.FOLLOW_UPS:
            return self.followup_agent.FollowUpAgentOutput(
                followups=[
                    self.followup_agent.FollowUpDraft(
                        subject="Launch plan",
                        body_html="<p>Here is the plan.</p>",
                        recipients=[
                            self.followup_agent.FollowUpRecipient(
                                name="Ravi", email="ravi@example.com"
                            )
                        ],
                    )
                ]
            )
        return self.insight_agent.InsightAgentOutput(
            insights=[
                self.insight_agent.InsightCandidate(
                    category=self.insight_agent.InsightCategory.RISK,
                    title="Launch timing risk",
                    description="The review date is not confirmed.",
                )
            ]
        )

    def _orchestrated_result(self, request, *, failed=None, outputs=None, ids=None):
        O = self.contracts.ProcessingOperation
        failed = failed or {}
        outputs = outputs or {}
        results = []
        for operation in request.requested_operations:
            if operation in failed:
                results.append(
                    self.results.OperationResult(
                        operation=operation,
                        status="failed",
                        error=self.results.ProcessingFailure(
                            code=failed[operation], message="Safe provider failure."
                        ),
                    )
                )
            else:
                results.append(
                    self.results.OperationResult(
                        operation=operation,
                        status="completed",
                        output=outputs.get(operation, self._output(operation)),
                    )
                )
        successes = sum(item.status == "completed" for item in results)
        status = (
            self.contracts.ProcessingStatus.COMPLETED
            if successes == len(results)
            else self.contracts.ProcessingStatus.FAILED
            if successes == 0
            else self.contracts.ProcessingStatus.PARTIALLY_FAILED
        )
        meeting_id, transcript_id = ids or (MEETING_ID, TRANSCRIPT_ID)
        return self.results.ProcessingResult(
            meeting_id=meeting_id,
            transcript_id=transcript_id,
            requested_operations=request.requested_operations,
            status=status,
            results=results,
        )

    def test_builder_and_existing_orchestrator_are_called_with_trusted_inputs(self) -> None:
        request = self._request(context={"project": "launch"})
        self.orchestrator.process.return_value = self._orchestrated_result(request)
        builder = MagicMock(wraps=self.transcript_mapping.build_agent_input)
        service = self.processing_module.AIProcessingService(
            self.orchestrator, input_builder=builder
        )

        result = asyncio.run(service.process(request, self._transcript()))

        builder.assert_called_once_with(self._transcript(), meeting_id=MEETING_ID)
        self.orchestrator.process.assert_awaited_once()
        passed_request, agent_input = self.orchestrator.process.await_args.args
        self.assertIs(passed_request, request)
        self.assertEqual(agent_input.meeting_id, MEETING_ID)
        self.assertEqual(agent_input.transcript.transcript_id, TRANSCRIPT_ID)
        self.assertEqual(agent_input.transcript.segments[0].speaker, "Ravi")
        self.assertEqual(result.meeting_id, MEETING_ID)
        self.assertEqual(result.transcript_id, TRANSCRIPT_ID)

    def test_requested_operations_keep_order_and_existing_duplicate_semantics(self) -> None:
        O = self.contracts.ProcessingOperation
        request = self._request([O.INSIGHTS, O.SUMMARY, O.INSIGHTS, O.TASKS])
        self.assertEqual(request.requested_operations, [O.INSIGHTS, O.SUMMARY, O.TASKS])
        self.orchestrator.process.return_value = self._orchestrated_result(request)

        result = asyncio.run(self.service.process(request, self._transcript()))

        self.orchestrator.process.assert_awaited_once()
        self.assertEqual(
            result.requested_operations, [O.INSIGHTS, O.SUMMARY, O.TASKS]
        )
        self.assertEqual([item.operation for item in result.results], result.requested_operations)

    def test_all_five_operations_map_to_domain_ready_inputs(self) -> None:
        O = self.contracts.ProcessingOperation
        operations = [O.SUMMARY, O.TASKS, O.DECISIONS, O.FOLLOW_UPS, O.INSIGHTS]
        request = self._request(operations)
        self.orchestrator.process.return_value = self._orchestrated_result(request)

        result = asyncio.run(self.service.process(request, self._transcript()))

        self.assertEqual(result.status, self.contracts.ProcessingStatus.COMPLETED)
        summary, tasks, decisions, followups, insights = [
            item.output for item in result.results
        ]
        self.assertEqual(summary.meeting_id, str(MEETING_ID))
        self.assertEqual(summary.key_topics, ["launch"])
        self.assertEqual(tasks.items[0].title, "Send launch plan")
        self.assertIsNone(tasks.items[0].assignee_id)
        self.assertEqual(decisions.items[0].participants, ["Ravi"])
        self.assertEqual(followups.items[0].recipients, ["ravi@example.com"])
        self.assertEqual(insights.items[0].title, "Launch timing risk")
        for output in (tasks, decisions, followups, insights):
            self.assertTrue(
                all(item.meeting_id == str(MEETING_ID) for item in output.items)
            )

    def test_empty_list_outputs_are_valid_for_all_collection_operations(self) -> None:
        O = self.contracts.ProcessingOperation
        operations = [O.TASKS, O.DECISIONS, O.FOLLOW_UPS, O.INSIGHTS]
        request = self._request(operations)
        empty_outputs = {
            O.TASKS: self.task_agent.TaskAgentOutput(tasks=[]),
            O.DECISIONS: self.decision_agent.DecisionAgentOutput(decisions=[]),
            O.FOLLOW_UPS: self.followup_agent.FollowUpAgentOutput(followups=[]),
            O.INSIGHTS: self.insight_agent.InsightAgentOutput(insights=[]),
        }
        self.orchestrator.process.return_value = self._orchestrated_result(
            request, outputs=empty_outputs
        )

        result = asyncio.run(self.service.process(request, self._transcript()))

        self.assertEqual(result.status, self.contracts.ProcessingStatus.COMPLETED)
        self.assertEqual(
            [item.output.items for item in result.results], [[], [], [], []]
        )

    def test_operation_failure_preserves_other_success_and_aggregate_is_partial(self) -> None:
        O = self.contracts.ProcessingOperation
        request = self._request([O.SUMMARY, O.TASKS])
        self.orchestrator.process.return_value = self._orchestrated_result(
            request,
            failed={O.TASKS: self.results.ProcessingErrorCode.PROVIDER_UNAVAILABLE},
        )

        result = asyncio.run(self.service.process(request, self._transcript()))

        self.assertEqual(result.status, self.contracts.ProcessingStatus.PARTIALLY_FAILED)
        self.assertEqual(result.results[0].status, self.results.OperationStatus.COMPLETED)
        self.assertEqual(result.results[0].output.content, "The launch plan is ready.")
        self.assertEqual(result.results[1].status, self.results.OperationStatus.FAILED)
        self.assertEqual(
            result.results[1].error.code,
            self.results.ProcessingErrorCode.PROVIDER_UNAVAILABLE,
        )

    def test_unsafe_task_date_becomes_mapping_failure_without_erasing_summary(self) -> None:
        O = self.contracts.ProcessingOperation
        request = self._request([O.SUMMARY, O.TASKS])
        outputs = {
            O.TASKS: self.task_agent.TaskAgentOutput(
                tasks=[
                    self.task_agent.TaskCandidate(
                        title="Send launch plan", due_date=date(2026, 10, 8)
                    )
                ]
            )
        }
        self.orchestrator.process.return_value = self._orchestrated_result(
            request, outputs=outputs
        )

        result = asyncio.run(self.service.process(request, self._transcript()))

        self.assertEqual(result.status, self.contracts.ProcessingStatus.PARTIALLY_FAILED)
        self.assertEqual(result.results[0].status, self.results.OperationStatus.COMPLETED)
        self.assertEqual(
            result.results[1].error.code,
            self.results.ProcessingErrorCode.DOMAIN_MAPPING_FAILED,
        )
        self.assertNotIn("2026-10-08", result.results[1].error.message)

    def test_mapper_exception_is_sanitized_and_distinct(self) -> None:
        O = self.contracts.ProcessingOperation
        request = self._request([O.SUMMARY])
        self.orchestrator.process.return_value = self._orchestrated_result(request)
        mapper = MagicMock(wraps=self.domain_mapping)
        mapper.map_summary_output.side_effect = RuntimeError("private provider payload")
        service = self.processing_module.AIProcessingService(
            self.orchestrator, output_mapper=mapper
        )

        result = asyncio.run(service.process(request, self._transcript()))

        self.assertEqual(result.status, self.contracts.ProcessingStatus.FAILED)
        self.assertEqual(
            result.results[0].error.code,
            self.results.ProcessingErrorCode.DOMAIN_MAPPING_FAILED,
        )
        self.assertNotIn("private provider payload", result.results[0].error.message)

    def test_provider_exception_from_orchestrator_is_sanitized(self) -> None:
        O = self.contracts.ProcessingOperation
        request = self._request([O.SUMMARY, O.TASKS])
        self.orchestrator.process.side_effect = RuntimeError("api-key=private-secret")

        result = asyncio.run(self.service.process(request, self._transcript()))

        self.assertEqual(result.status, self.contracts.ProcessingStatus.FAILED)
        self.assertTrue(
            all(item.error.code == self.results.ProcessingErrorCode.UNEXPECTED_FAILURE
                for item in result.results)
        )
        self.assertNotIn("private-secret", str(result.model_dump()))

    def test_known_provider_failure_from_orchestrator_keeps_safe_error_contract(self) -> None:
        from llm.errors import ModelTimeoutError

        O = self.contracts.ProcessingOperation
        request = self._request([O.SUMMARY])
        self.orchestrator.process.side_effect = ModelTimeoutError()

        result = asyncio.run(self.service.process(request, self._transcript()))

        self.assertEqual(
            result.results[0].error.code,
            self.results.ProcessingErrorCode.PROVIDER_TIMEOUT,
        )
        self.assertEqual(result.results[0].error.message, "The model request timed out.")

    def test_transcript_id_mismatch_fails_all_requested_operations_without_orchestration(self) -> None:
        O = self.contracts.ProcessingOperation
        request = self._request([O.SUMMARY, O.TASKS])
        wrong_transcript = self._transcript(transcript_id=UUID(int=5))

        result = asyncio.run(self.service.process(request, wrong_transcript))

        self.orchestrator.process.assert_not_awaited()
        self.assertEqual(result.status, self.contracts.ProcessingStatus.FAILED)
        self.assertTrue(
            all(item.error.code == self.results.ProcessingErrorCode.INVALID_INPUT
                for item in result.results)
        )

    def test_builder_cannot_return_agent_input_with_forged_identity(self) -> None:
        O = self.contracts.ProcessingOperation
        request = self._request()
        correct_input = self.transcript_mapping.build_agent_input(
            self._transcript(), meeting_id=MEETING_ID
        )
        wrong_input = correct_input.model_copy(update={"meeting_id": UUID(int=99)})
        builder = MagicMock(return_value=wrong_input)
        service = self.processing_module.AIProcessingService(
            self.orchestrator, input_builder=builder
        )

        result = asyncio.run(service.process(request, self._transcript()))

        self.orchestrator.process.assert_not_awaited()
        self.assertEqual(
            result.results[0].error.code,
            self.results.ProcessingErrorCode.INVALID_INPUT,
        )

    def test_orchestrator_result_with_mismatched_identity_is_rejected(self) -> None:
        O = self.contracts.ProcessingOperation
        request = self._request()
        self.orchestrator.process.return_value = self._orchestrated_result(
            request, ids=(UUID(int=99), TRANSCRIPT_ID)
        )

        result = asyncio.run(self.service.process(request, self._transcript()))

        self.assertEqual(result.status, self.contracts.ProcessingStatus.FAILED)
        self.assertEqual(
            result.results[0].error.code,
            self.results.ProcessingErrorCode.UNEXPECTED_FAILURE,
        )

    def test_invalid_mapper_return_type_becomes_controlled_mapping_failure(self) -> None:
        O = self.contracts.ProcessingOperation
        request = self._request()
        self.orchestrator.process.return_value = self._orchestrated_result(request)
        mapper = MagicMock(wraps=self.domain_mapping)
        mapper.map_summary_output.return_value = []
        service = self.processing_module.AIProcessingService(
            self.orchestrator, output_mapper=mapper
        )

        result = asyncio.run(service.process(request, self._transcript()))

        self.assertEqual(
            result.results[0].error.code,
            self.results.ProcessingErrorCode.DOMAIN_MAPPING_FAILED,
        )

    def test_processing_service_has_no_database_or_repository_dependency(self) -> None:
        source = Path(self.processing_module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = [
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        ] + [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        forbidden = ("sqlalchemy", "repository", "database", "openai")
        self.assertFalse(
            any(term in name.lower() for name in imports for term in forbidden)
        )
        self.assertFalse(hasattr(self.service, "_session"))


if __name__ == "__main__":
    unittest.main()
