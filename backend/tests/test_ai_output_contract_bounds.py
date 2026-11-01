"""Finite, explicit output contracts for AI-generated structured data."""

from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

from pydantic import ValidationError


BACKEND_ROOT = Path(__file__).resolve().parents[1]
AI_SERVICE_ROOT = BACKEND_ROOT / "ai-service"
for _service in ("gateway-service", "meeting-service", "ai-service", "search-service"):
    _path = str(BACKEND_ROOT / _service)
    while _path in sys.path:
        sys.path.remove(_path)
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(AI_SERVICE_ROOT))


class AIOutputContractBoundsTestCase(unittest.TestCase):
    """Check schema validation rejects outputs beyond the stated product caps."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.summary = importlib.import_module("agents.summary_agent").SummaryAgentOutput
        task = importlib.import_module("agents.task_agent")
        cls.task = task.TaskAgentOutput
        cls.task_item = task.TaskCandidate
        decision = importlib.import_module("agents.decision_agent")
        cls.decision = decision.DecisionAgentOutput
        cls.decision_item = decision.DecisionCandidate
        followup = importlib.import_module("agents.followup_agent")
        cls.followup = followup.FollowUpAgentOutput
        cls.followup_item = followup.FollowUpDraft
        cls.recipient = followup.FollowUpRecipient
        insight = importlib.import_module("agents.insight_agent")
        cls.insight = insight.InsightAgentOutput
        cls.insight_item = insight.InsightCandidate
        cls.category = insight.InsightCategory
        cls.cross_meeting = importlib.import_module(
            "agents.cross_meeting_agent"
        ).CrossMeetingAnswerOutput

    def assert_rejected(self, model, **payload) -> None:
        with self.assertRaises(ValidationError):
            model(**payload)

    def test_summary_bounds(self) -> None:
        self.assert_rejected(self.summary, content="x" * 8001, key_topics=[])
        self.assert_rejected(self.summary, content="ok", key_topics=["topic"] * 21)
        self.assert_rejected(self.summary, content="ok", key_topics=["x" * 121])

    def test_task_bounds(self) -> None:
        self.assert_rejected(self.task, tasks=[{"title": "task"}] * 101)
        self.assert_rejected(self.task_item, title="x" * 301)
        self.assert_rejected(self.task_item, title="task", description="x" * 2001)
        self.assert_rejected(self.task_item, title="task", assignee_name="x" * 201)

    def test_decision_bounds(self) -> None:
        self.assert_rejected(self.decision, decisions=[{"statement": "yes"}] * 101)
        self.assert_rejected(self.decision_item, statement="x" * 1001)
        self.assert_rejected(self.decision_item, statement="yes", context="x" * 2001)
        self.assert_rejected(
            self.decision_item, statement="yes", participants=["speaker"] * 51
        )
        self.assert_rejected(
            self.decision_item, statement="yes", participants=["x" * 201]
        )

    def test_followup_bounds(self) -> None:
        self.assert_rejected(self.followup, followups=[{"subject": "s", "body_html": "b", "recipients": []}] * 21)
        self.assert_rejected(self.followup_item, subject="x" * 201, body_html="body", recipients=[])
        self.assert_rejected(self.followup_item, subject="subject", body_html="x" * 8001, recipients=[])
        self.assert_rejected(
            self.followup_item,
            subject="subject",
            body_html="body",
            recipients=[{"name": "speaker"}] * 21,
        )
        self.assert_rejected(self.recipient, name="x" * 201)
        self.assert_rejected(self.recipient, email=f"{'x' * 244}@example.com")

    def test_insight_bounds(self) -> None:
        self.assert_rejected(
            self.insight,
            insights=[{"category": self.category.OBSERVATION, "title": "t", "description": "d"}] * 51,
        )
        self.assert_rejected(
            self.insight_item,
            category=self.category.OBSERVATION,
            title="x" * 301,
            description="description",
        )
        self.assert_rejected(
            self.insight_item,
            category=self.category.OBSERVATION,
            title="title",
            description="x" * 2001,
        )

    def test_cross_meeting_answer_bounds(self) -> None:
        self.assert_rejected(
            self.cross_meeting, answer="x" * 8001, insufficient_evidence=True, evidence_ids=[]
        )
        self.assert_rejected(
            self.cross_meeting,
            answer="answer",
            insufficient_evidence=True,
            evidence_ids=["record"] * 101,
        )
        self.assert_rejected(
            self.cross_meeting,
            answer="answer",
            insufficient_evidence=True,
            evidence_ids=["x" * 65],
        )


if __name__ == "__main__":
    unittest.main()
