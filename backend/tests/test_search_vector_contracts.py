"""Phase 10.1 vector-search contracts; no external embedding/Qdrant services."""

from __future__ import annotations

import importlib
import subprocess
import sys
import textwrap
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SEARCH_ROOT = BACKEND_ROOT / "search-service"
MEETING_ID = UUID("d146f98d-d557-4b89-a746-3e48e73d46b1")
TRANSCRIPT_ID = UUID("084c3a14-1a7f-41c9-a7c8-1e195aa5313a")
OWNER_ID = UUID("10000000-0000-0000-0000-000000000001")
ORGANIZATION_ID = UUID("20000000-0000-0000-0000-000000000002")


def _prepare_search_imports() -> None:
    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            del sys.modules[module_name]
        elif module_name.split(".", 1)[0] in {"chunking", "embeddings", "vectorstore"}:
            del sys.modules[module_name]
    for service in ("gateway-service", "meeting-service", "ai-service", "search-service"):
        root = str(BACKEND_ROOT / service)
        while root in sys.path:
            sys.path.remove(root)
    sys.path[:0] = [str(SEARCH_ROOT), str(BACKEND_ROOT)]


class SearchVectorContractTests(unittest.TestCase):
    def setUp(self) -> None:
        _prepare_search_imports()
        from shared.schemas.transcript import NormalizedTranscript, TranscriptInDB
        from shared.transcripts.normalization import normalize_transcript
        from chunking.contracts import TranscriptIndexScope
        from chunking.transcript_chunker import TranscriptChunker, transcript_chunk_id
        from embeddings.contracts import (
            EmbeddingModelIdentity,
            EmbeddingRequest,
            EmbeddingResponse,
        )
        from app.config.settings import SearchSettings

        self.NormalizedTranscript = NormalizedTranscript
        self.TranscriptInDB = TranscriptInDB
        self.normalize_transcript = normalize_transcript
        self.TranscriptIndexScope = TranscriptIndexScope
        self.TranscriptChunker = TranscriptChunker
        self.transcript_chunk_id = transcript_chunk_id
        self.EmbeddingModelIdentity = EmbeddingModelIdentity
        self.EmbeddingRequest = EmbeddingRequest
        self.EmbeddingResponse = EmbeddingResponse
        self.SearchSettings = SearchSettings
        now = datetime(2026, 10, 3, tzinfo=timezone.utc)
        self.transcript_dto = TranscriptInDB(
            id=str(TRANSCRIPT_ID),
            meeting_id=str(MEETING_ID),
            language="en-US",
            segments=[
                {"index": 4, "speaker": "Bo", "text": "Ship Friday.", "start_ms": 220, "end_ms": 350},
                {"index": 2, "speaker": "Ada", "text": "We agreed.", "start_ms": 100, "end_ms": 200},
            ],
            created_at=now,
            updated_at=now,
        )
        self.normalized = self.normalize_transcript(
            self.transcript_dto,
            meeting_id=MEETING_ID,
        )
        self.scope = self.TranscriptIndexScope(
            meeting_id=MEETING_ID,
            transcript_id=TRANSCRIPT_ID,
            owner_id=OWNER_ID,
            organization_id=ORGANIZATION_ID,
        )

    def test_existing_normalizer_is_the_ordered_search_source(self) -> None:
        self.assertEqual(self.normalized.meeting_id, MEETING_ID)
        self.assertEqual(self.normalized.transcript_id, TRANSCRIPT_ID)
        self.assertEqual([segment.index for segment in self.normalized.segments], [2, 4])
        self.assertEqual(self.normalized.language, "en-US")

    def test_normalized_transcript_contract_rejects_noncanonical_segment_order(self) -> None:
        with self.assertRaises(ValidationError):
            self.NormalizedTranscript(
                meeting_id=MEETING_ID,
                transcript_id=TRANSCRIPT_ID,
                language="en",
                segments=[
                    {"index": 4, "text": "Later."},
                    {"index": 2, "text": "Earlier."},
                ],
            )

    def test_chunk_metadata_and_identity_are_deterministic(self) -> None:
        chunker = self.TranscriptChunker(max_characters=100)
        first = chunker.chunk(self.normalized, scope=self.scope)
        second = chunker.chunk(self.normalized, scope=self.scope)

        self.assertEqual(first, second)
        self.assertEqual(len(first), 1)
        chunk = first[0]
        self.assertEqual(chunk.chunk_id, self.transcript_chunk_id(MEETING_ID, TRANSCRIPT_ID, 0))
        self.assertEqual(chunk.meeting_id, MEETING_ID)
        self.assertEqual(chunk.transcript_id, TRANSCRIPT_ID)
        self.assertEqual(chunk.owner_id, OWNER_ID)
        self.assertEqual(chunk.organization_id, ORGANIZATION_ID)
        self.assertEqual(chunk.chunk_index, 0)
        self.assertEqual([segment.index for segment in chunk.source_segments], [2, 4])
        self.assertEqual([segment.speaker for segment in chunk.source_segments], ["Ada", "Bo"])
        self.assertEqual(
            [(segment.start_ms, segment.end_ms) for segment in chunk.source_segments],
            [(100, 200), (220, 350)],
        )
        self.assertEqual((chunk.start_ms, chunk.end_ms), (100, 350))
        self.assertEqual(chunk.language, "en-US")
        self.assertEqual(chunk.text, "We agreed.\nShip Friday.")
        self.assertNotIn("title", chunk.model_dump())

    def test_chunking_uses_ordered_segment_boundaries_and_does_not_truncate_long_segments(self) -> None:
        chunker = self.TranscriptChunker(max_characters=10)
        chunks = chunker.chunk(self.normalized, scope=self.scope)

        self.assertEqual([item.chunk_index for item in chunks], [0, 1])
        self.assertEqual([[segment.index for segment in item.source_segments] for item in chunks], [[2], [4]])
        self.assertEqual(chunks[1].text, "Ship Friday.")
        self.assertEqual(chunks[1].chunk_id, self.transcript_chunk_id(MEETING_ID, TRANSCRIPT_ID, 1))

    def test_point_identity_is_stable_for_reindex_and_separate_by_source_position(self) -> None:
        chunker = self.TranscriptChunker(max_characters=100)
        original_chunk = chunker.chunk(self.normalized, scope=self.scope)[0]
        updated_dto = self.transcript_dto.model_copy(
            update={
                "segments": [
                    {"index": 2, "speaker": "Ada", "text": "We agreed on a revised plan."},
                    {"index": 4, "speaker": "Bo", "text": "Ship Friday."},
                ]
            }
        )
        updated = self.normalize_transcript(updated_dto, meeting_id=MEETING_ID)
        updated_chunk = chunker.chunk(updated, scope=self.scope)[0]
        original = original_chunk.chunk_id
        self.assertNotEqual(original_chunk.text, updated_chunk.text)
        self.assertEqual(original, updated_chunk.chunk_id)
        self.assertNotEqual(original, self.transcript_chunk_id(MEETING_ID, TRANSCRIPT_ID, 1))
        self.assertNotEqual(
            original,
            self.transcript_chunk_id(MEETING_ID, UUID("084c3a14-1a7f-41c9-a7c8-1e195aa5313b"), 0),
        )

    def test_scope_must_match_normalized_meeting_and_transcript(self) -> None:
        bad_scope = self.scope.model_copy(update={"meeting_id": UUID("d146f98d-d557-4b89-a746-3e48e73d46b2")})
        with self.assertRaisesRegex(ValueError, "scope must match"):
            self.TranscriptChunker().chunk(self.normalized, scope=bad_scope)

    def test_chunk_payload_requires_identity_owner_and_order_metadata(self) -> None:
        from chunking.contracts import TranscriptChunk, TranscriptChunkSegment

        with self.assertRaises(ValidationError):
            TranscriptChunk(
                chunk_id=self.transcript_chunk_id(MEETING_ID, TRANSCRIPT_ID, 0),
                meeting_id=MEETING_ID,
                transcript_id=TRANSCRIPT_ID,
                organization_id=ORGANIZATION_ID,
                chunk_index=0,
                source_segments=[{"index": 2}],
                text="Content",
            )

        with self.assertRaises(ValidationError):
            TranscriptChunkSegment(index=2, start_ms=300, end_ms=200)
        with self.assertRaises(ValueError):
            self.transcript_chunk_id(MEETING_ID, TRANSCRIPT_ID, -1)

        with self.assertRaises(ValidationError):
            self.TranscriptIndexScope(
                meeting_id=MEETING_ID,
                transcript_id=TRANSCRIPT_ID,
                organization_id=ORGANIZATION_ID,
            )
        with self.assertRaises(ValidationError):
            TranscriptChunk(
                chunk_id=self.transcript_chunk_id(MEETING_ID, TRANSCRIPT_ID, 0),
                meeting_id=MEETING_ID,
                transcript_id=TRANSCRIPT_ID,
                owner_id=OWNER_ID,
                organization_id=ORGANIZATION_ID,
                chunk_index=0,
                source_segments=[{"index": 2}, {"index": 2}],
                text="Content",
            )

    def test_invalid_embedding_dimensions_and_nonfinite_vectors_are_rejected(self) -> None:
        identity = self.EmbeddingModelIdentity(
            provider="provider-x",
            model="model-y",
            dimensions=3,
        )
        request = self.EmbeddingRequest(model_identity=identity, texts=["transcript text"])
        self.assertEqual(request.model_identity, identity)
        with self.assertRaises(ValidationError):
            self.EmbeddingResponse(model_identity=identity, vectors=[[0.1, 0.2]])
        with self.assertRaises(ValidationError):
            self.EmbeddingResponse(model_identity=identity, vectors=[[0.1, float("nan"), 0.3]])
        with self.assertRaises(ValidationError):
            self.EmbeddingModelIdentity(provider=" ", model="model-y", dimensions=3)
        with self.assertRaises(ValidationError):
            self.EmbeddingRequest(model_identity=identity, texts=["  "])

    def test_search_configuration_defaults_and_invalid_values(self) -> None:
        settings = self.SearchSettings()
        self.assertEqual(settings.qdrant_collection_name, "meeting_chunks")
        self.assertEqual(settings.qdrant_distance_metric, "Cosine")
        self.assertEqual(settings.embedding_provider, "openai")
        self.assertEqual(settings.embedding_model, "text-embedding-3-small")
        self.assertEqual(settings.embedding_dimensions, 1536)

        configured = self.SearchSettings(
            qdrant_url="https://vectors.example.test/",
            qdrant_collection_name="meeting-chunks-v2",
            qdrant_distance_metric="Dot",
            embedding_provider="provider-x",
            embedding_model="model-y",
            embedding_dimensions=3,
            transcript_chunk_max_characters=256,
        )
        self.assertEqual(configured.qdrant_url, "https://vectors.example.test")
        self.assertEqual(configured.embedding_dimensions, 3)
        for invalid in (
            {"qdrant_url": "file:///tmp/qdrant"},
            {"qdrant_url": "https://user:pass@vectors.example.test"},
            {"qdrant_collection_name": "bad name"},
            {"qdrant_distance_metric": "Chebyshev"},
            {"embedding_provider": "   "},
            {"embedding_model": ""},
            {"embedding_dimensions": 0},
            {"transcript_chunk_max_characters": 0},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                self.SearchSettings(**invalid)

    def test_contracts_and_chunking_do_not_connect_to_or_import_qdrant(self) -> None:
        script = textwrap.dedent("""
            import sys
            from pathlib import Path
            backend_root, search_root = map(Path, sys.argv[1:])
            sys.path[:0] = [str(search_root), str(backend_root)]
            import app.config.settings
            import chunking.contracts
            import chunking.transcript_chunker
            import indexing.contracts
            import indexing.pipeline
            assert not any(
                name == "qdrant_client" or name.startswith("qdrant_client.")
                for name in sys.modules
            )
        """)
        result = subprocess.run(
            [sys.executable, "-c", script, str(BACKEND_ROOT), str(SEARCH_ROOT)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
