"""Transcript DTO normalization tests at the AI service boundary."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

BACKEND_ROOT = Path(__file__).resolve().parents[1]
AI_SERVICE_ROOT = BACKEND_ROOT / "ai-service"
MEETING_ID = UUID("d146f98d-d557-4b89-a746-3e48e73d46b1")
TRANSCRIPT_ID = UUID("084c3a14-1a7f-41c9-a7c8-1e195aa5313a")
OTHER_MEETING_ID = UUID("d146f98d-d557-4b89-a746-3e48e73d46b2")
OTHER_TRANSCRIPT_ID = UUID("084c3a14-1a7f-41c9-a7c8-1e195aa5313b")


def _prepare_imports() -> None:
    for module_name in list(sys.modules):
        if any(
            module_name == package or module_name.startswith(f"{package}.")
            for package in ("app", "agents", "llm", "pipelines")
        ):
            del sys.modules[module_name]
    for service in ("gateway-service", "meeting-service", "ai-service"):
        root = str(BACKEND_ROOT / service)
        while root in sys.path:
            sys.path.remove(root)
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    sys.path.insert(0, str(AI_SERVICE_ROOT))


class TranscriptMappingTestCase(unittest.TestCase):
    def setUp(self) -> None:
        _prepare_imports()
        self.transcript_schema = importlib.import_module(
            "shared.schemas.transcript"
        )
        self.contracts = importlib.import_module("app.contracts")
        self.mapping = importlib.import_module("app.transcript_mapping")

    def _dto(self, *, segments=None, language="en", meeting_id=MEETING_ID,
             transcript_id=TRANSCRIPT_ID):
        now = datetime(2026, 10, 1, tzinfo=timezone.utc)
        if segments is None:
            segments = [
                {
                    "index": 1,
                    "speaker": "Ravi",
                    "text": "We will ship next week.",
                    "start_ms": 1250,
                    "end_ms": 2400,
                },
                {
                    "index": 0,
                    "speaker": "Meghna",
                    "text": "The release is ready.",
                    "start_ms": 100,
                    "end_ms": 900,
                },
            ]
        return self.transcript_schema.TranscriptInDB(
            id=str(transcript_id),
            meeting_id=str(meeting_id),
            segments=segments,
            language=language,
            created_at=now,
            updated_at=now,
        )

    def _build(self, transcript=None, **kwargs):
        return self.mapping.build_agent_input(
            transcript or self._dto(), meeting_id=MEETING_ID, **kwargs
        )

    def test_multiple_segments_are_sorted_by_index_with_content_metadata_preserved(self):
        result = self._build()

        segments = result.transcript.segments
        self.assertEqual([segment.index for segment in segments], [0, 1])
        self.assertEqual(
            [segment.text for segment in segments],
            ["The release is ready.", "We will ship next week."],
        )
        self.assertEqual(segments[0].speaker, "Meghna")
        self.assertEqual(segments[0].start_ms, 100)
        self.assertEqual(segments[0].end_ms, 900)
        self.assertEqual(segments[1].speaker, "Ravi")
        self.assertEqual(segments[1].start_ms, 1250)
        self.assertEqual(segments[1].end_ms, 2400)
        self.assertEqual(result.transcript.language, "en")

    def test_normalization_is_deterministic_and_does_not_rewrite_or_truncate_text(self):
        transcript = self._dto(
            segments=[
                {"index": 3, "text": "  Raw source text — keep exactly.  "},
                {"index": 2, "text": "Second in sequence."},
            ]
        )

        first = self._build(transcript)
        second = self._build(transcript)

        self.assertEqual(first.model_dump(), second.model_dump())
        self.assertEqual(
            [segment.text for segment in first.transcript.segments],
            ["Second in sequence.", "  Raw source text — keep exactly.  "],
        )

    def test_empty_transcript_is_rejected(self):
        with self.assertRaises(self.mapping.TranscriptNormalizationError):
            self._build(self._dto(segments=[]))

    def test_invalid_segment_fields_are_rejected(self):
        invalid_segments = (
            [{"index": -1, "text": "Invalid sequence."}],
            [{"index": 0, "text": "Duplicate."}, {"index": 0, "text": "Index."}],
            [{"index": 0, "text": "Negative start.", "start_ms": -1}],
            [{"index": 0, "text": "Reversed.", "start_ms": 20, "end_ms": 10}],
        )
        for segments in invalid_segments:
            with self.subTest(segments=segments), self.assertRaises(
                self.mapping.TranscriptNormalizationError
            ):
                self._build(self._dto(segments=segments))

    def test_whitespace_only_transcript_is_rejected(self):
        with self.assertRaises(self.mapping.TranscriptNormalizationError):
            self._build(self._dto(segments=[{"index": 0, "text": " \t\n "}]))

    def test_speaker_and_timestamps_are_optional(self):
        result = self._build(
            self._dto(segments=[{"index": 0, "text": "No optional metadata."}])
        )

        segment = result.transcript.segments[0]
        self.assertIsNone(segment.speaker)
        self.assertIsNone(segment.start_ms)
        self.assertIsNone(segment.end_ms)

    def test_agent_input_contract_accepts_nullable_language(self):
        content = self.contracts.TranscriptContent(
            transcript_id=TRANSCRIPT_ID,
            language=None,
            segments=[{"index": 0, "text": "Language is unknown."}],
        )

        self.assertIsNone(content.language)

    def test_mapper_preserves_language_value_from_existing_domain_dto(self):
        result = self._build(self._dto(language="fr"))
        self.assertEqual(result.transcript.language, "fr")

    def test_meeting_and_transcript_identity_are_preserved(self):
        result = self._build()

        self.assertEqual(result.meeting_id, MEETING_ID)
        self.assertEqual(result.transcript.transcript_id, TRANSCRIPT_ID)

    def test_transcript_from_another_meeting_is_rejected(self):
        with self.assertRaises(self.mapping.TranscriptNormalizationError):
            self._build(self._dto(meeting_id=OTHER_MEETING_ID))

    def test_invalid_transcript_identifier_is_rejected(self):
        with self.assertRaises(self.mapping.TranscriptNormalizationError):
            self._build(self._dto(transcript_id="not-a-uuid"))

    def test_agent_input_contains_only_safe_normalized_data_not_orm_or_meeting_metadata(self):
        result = self._build()
        payload = result.model_dump(mode="json")

        self.assertEqual(set(payload), {"meeting_id", "transcript", "meeting_context"})
        self.assertEqual(
            set(payload["transcript"]), {"transcript_id", "language", "segments"}
        )
        self.assertNotIn("created_at", str(payload))
        self.assertNotIn("updated_at", str(payload))
        self.assertNotIn("organization_id", str(payload))
        self.assertNotIn("created_by", str(payload))
        self.assertNotIn("session", str(payload))

    def test_supported_empty_context_stays_empty(self):
        self.assertIsNone(self._build().meeting_context)

    def test_agent_input_from_mapper_is_accepted_by_all_five_agents(self):
        async def run():
            contracts = self.contracts
            agent_input = self._build()
            request = contracts.ProcessingRequest(
                meeting_id=MEETING_ID,
                transcript_id=TRANSCRIPT_ID,
                requested_operations=[
                    "summary", "tasks", "decisions", "follow_ups", "insights"
                ],
            )

            class FakeProvider:
                async def generate(self, model_request):
                    outputs = {
                        "SummaryAgentOutput": '{"content":"Summary","key_topics":[]}',
                        "TaskAgentOutput": '{"tasks":[]}',
                        "DecisionAgentOutput": '{"decisions":[]}',
                        "FollowUpAgentOutput": '{"followups":[]}',
                        "InsightAgentOutput": '{"insights":[]}',
                    }
                    return contracts.ModelResponse(
                        content=outputs[model_request.response_schema["title"]]
                    )

            orchestrator = importlib.import_module("agents.orchestrator")
            result = await orchestrator.AIProcessingOrchestrator(FakeProvider()).process(
                request, agent_input
            )
            self.assertEqual(result.status, contracts.ProcessingStatus.COMPLETED)
            self.assertEqual(len(result.results), 5)

        import asyncio

        asyncio.run(run())

    def test_orchestrator_rejects_mismatched_meeting_identity(self):
        async def run():
            request = self.contracts.ProcessingRequest(
                meeting_id=OTHER_MEETING_ID,
                transcript_id=TRANSCRIPT_ID,
                requested_operations=["summary"],
            )
            orchestrator = importlib.import_module("agents.orchestrator")
            with self.assertRaises(ValueError):
                await orchestrator.AIProcessingOrchestrator().process(
                    request, self._build()
                )

        import asyncio

        asyncio.run(run())

    def test_orchestrator_rejects_mismatched_transcript_identity(self):
        async def run():
            request = self.contracts.ProcessingRequest(
                meeting_id=MEETING_ID,
                transcript_id=OTHER_TRANSCRIPT_ID,
                requested_operations=["summary"],
            )
            orchestrator = importlib.import_module("agents.orchestrator")
            with self.assertRaises(ValueError):
                await orchestrator.AIProcessingOrchestrator().process(
                    request, self._build()
                )

        import asyncio

        asyncio.run(run())

    def test_mapping_import_does_not_load_database_or_provider_sdk(self):
        guarded_script = """
import builtins
real_import = builtins.__import__
blocked = ('sqlalchemy', 'openai', 'google', 'httpx', 'requests')
def guarded_import(name, *args, **kwargs):
    if any(name == root or name.startswith(root + '.') for root in blocked):
        raise AssertionError('Transcript mapping imported database/provider/network code')
    return real_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
from app.transcript_mapping import build_agent_input
assert build_agent_input
"""
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            (str(AI_SERVICE_ROOT), str(BACKEND_ROOT))
        )
        result = subprocess.run(
            [sys.executable, "-c", guarded_script],
            cwd=BACKEND_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
