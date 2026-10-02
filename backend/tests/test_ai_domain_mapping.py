"""Focused tests for the AI output to existing domain input boundary."""

from __future__ import annotations

import ast
import importlib
import sys
import unittest
from datetime import date
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
AI_SERVICE_ROOT = BACKEND_ROOT / "ai-service"
MEETING_ID = UUID("d146f98d-d557-4b89-a746-3e48e73d46b1")


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


class AIDomainMappingTests(unittest.TestCase):
    def setUp(self) -> None:
        _prepare_imports()
        self.mapping = importlib.import_module("app.domain_mapping")
        self.summary = importlib.import_module("agents.summary_agent")
        self.task = importlib.import_module("agents.task_agent")
        self.decision = importlib.import_module("agents.decision_agent")
        self.followup = importlib.import_module("agents.followup_agent")
        self.insight = importlib.import_module("agents.insight_agent")

    def test_summary_maps_content_topics_and_uses_trusted_identity(self) -> None:
        result = self.mapping.map_summary_output(
            self.summary.SummaryAgentOutput(
                content="Launch is planned.", key_topics=["launch"]
            ),
            meeting_id=MEETING_ID,
        )
        self.assertEqual(result.meeting_id, str(MEETING_ID))
        self.assertEqual(result.content, "Launch is planned.")
        self.assertEqual(result.key_topics, ["launch"])
        self.assertNotIn("id", result.model_fields)
        self.assertNotIn("version", result.model_fields)
        self.assertIsNone(result.model_provider)
        with self.assertRaises(ValidationError):
            self.summary.SummaryAgentOutput.model_validate(
                {"content": "x", "key_topics": [], "meeting_id": str(MEETING_ID)}
            )

    def test_task_maps_supported_fields_without_assigning_identity_or_status(self) -> None:
        output = self.task.TaskAgentOutput(
            tasks=[
                self.task.TaskCandidate(
                    title="Send notes", description="Share the notes", assignee_name="Ravi"
                )
            ]
        )
        result = self.mapping.map_task_output(output, meeting_id=MEETING_ID)[0]
        self.assertEqual(result.meeting_id, str(MEETING_ID))
        self.assertEqual(result.title, "Send notes")
        self.assertEqual(result.description, "Share the notes")
        self.assertIsNone(result.assignee_id)
        self.assertIsNone(result.due_at)
        self.assertNotIn("status", result.model_fields)
        self.assertEqual(output.tasks[0].assignee_name, "Ravi")

    def test_explicit_calendar_due_date_is_rejected_without_inventing_time(self) -> None:
        output = self.task.TaskAgentOutput(
            tasks=[self.task.TaskCandidate(title="Send notes", due_date=date(2026, 11, 3))]
        )
        with self.assertRaisesRegex(
            self.mapping.AIOutputMappingError, "datetime domain contract"
        ):
            self.mapping.map_task_output(output, meeting_id=MEETING_ID)

    def test_decision_names_and_empty_participants_are_preserved_as_text(self) -> None:
        output = self.decision.DecisionAgentOutput(
            decisions=[
                self.decision.DecisionCandidate(
                    statement="Use option A", context="Lower cost", participants=["Ravi"]
                ),
                self.decision.DecisionCandidate(statement="Defer launch"),
            ]
        )
        results = self.mapping.map_decision_output(output, meeting_id=MEETING_ID)
        self.assertEqual(results[0].statement, "Use option A")
        self.assertEqual(results[0].context, "Lower cost")
        self.assertEqual(results[0].participants, ["Ravi"])
        self.assertEqual(results[1].participants, [])
        self.assertEqual(results[0].meeting_id, str(MEETING_ID))

    def test_followup_maps_explicit_email_only_and_has_no_lifecycle_fields(self) -> None:
        output = self.followup.FollowUpAgentOutput(
            followups=[
                self.followup.FollowUpDraft(
                    subject="Notes",
                    body_html="<p>Here are the notes.</p>",
                    recipients=[
                        self.followup.FollowUpRecipient(
                            name="Ravi", email="ravi@example.com"
                        )
                    ],
                )
            ]
        )
        result = self.mapping.map_followup_output(output, meeting_id=MEETING_ID)[0]
        self.assertEqual(result.recipients, ["ravi@example.com"])
        self.assertEqual(result.subject, "Notes")
        self.assertEqual(result.body_html, "<p>Here are the notes.</p>")
        self.assertNotIn("status", result.model_fields)
        self.assertNotIn("sent_at", result.model_fields)

    def test_followup_name_without_email_is_rejected_not_discarded_or_invented(self) -> None:
        output = self.followup.FollowUpAgentOutput(
            followups=[
                self.followup.FollowUpDraft(
                    subject="Notes",
                    body_html="<p>Notes</p>",
                    recipients=[self.followup.FollowUpRecipient(name="Ravi")],
                )
            ]
        )
        with self.assertRaisesRegex(
            self.mapping.AIOutputMappingError, "email-only domain contract"
        ):
            self.mapping.map_followup_output(output, meeting_id=MEETING_ID)

    def test_insights_remain_typed_application_results(self) -> None:
        output = self.insight.InsightAgentOutput(
            insights=[
                self.insight.InsightCandidate(
                    category=self.insight.InsightCategory.RISK,
                    title="Review may slip",
                    description="The review is not scheduled.",
                )
            ]
        )
        results = self.mapping.map_insight_output(output, meeting_id=MEETING_ID)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].meeting_id, str(MEETING_ID))
        self.assertEqual(results[0].category, self.insight.InsightCategory.RISK)
        self.assertEqual(results[0].title, "Review may slip")
        self.assertEqual(results[0].description, "The review is not scheduled.")
        self.assertNotIn("id", results[0].model_fields)
        self.assertNotIn("created_at", results[0].model_fields)

    def test_empty_insight_output_maps_to_no_domain_rows(self) -> None:
        output = self.insight.InsightAgentOutput(insights=[])
        self.assertEqual(
            self.mapping.map_insight_output(output, meeting_id=MEETING_ID), []
        )

    def test_unexpected_or_malformed_output_and_bad_trusted_context_are_rejected(self) -> None:
        with self.assertRaises(self.mapping.AIOutputMappingError):
            self.mapping.map_summary_output(
                {"content": "ok", "key_topics": [], "summary_id": "forged"},
                meeting_id=MEETING_ID,
            )
        with self.assertRaises(self.mapping.AIOutputMappingError):
            self.mapping.map_summary_output(
                {"content": " ", "key_topics": []},
                meeting_id=MEETING_ID,
            )
        with self.assertRaises(self.mapping.AIOutputMappingError):
            self.mapping.map_summary_output(
                self.summary.SummaryAgentOutput(content="ok", key_topics=[]),
                meeting_id="not-a-uuid",
            )

    def test_mapper_has_no_persistence_or_provider_dependencies(self) -> None:
        source = Path(self.mapping.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ] + [
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        ]
        forbidden = ("sqlalchemy", "repository", "database", "llm", "openai")
        self.assertFalse(any(term in module.lower() for module in imports for term in forbidden))


if __name__ == "__main__":
    unittest.main()
