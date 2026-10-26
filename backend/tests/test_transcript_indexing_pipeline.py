"""Phase 10.3 deterministic transcript index preparation tests; no Qdrant/API."""

from __future__ import annotations

import importlib
import subprocess
import sys
import textwrap
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from pydantic import SecretStr, ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SEARCH_ROOT = BACKEND_ROOT / "search-service"
MEETING_ID = UUID("d146f98d-d557-4b89-a746-3e48e73d46b1")
TRANSCRIPT_ID = UUID("084c3a14-1a7f-41c9-a7c8-1e195aa5313a")
OWNER_ID = UUID("10000000-0000-0000-0000-000000000001")
ORG_ID = UUID("20000000-0000-0000-0000-000000000002")


def _prepare_search_imports() -> None:
    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            del sys.modules[module_name]
        elif module_name.split(".", 1)[0] in {
            "chunking", "embeddings", "indexing", "vectorstore"
        }:
            del sys.modules[module_name]
    for service in ("gateway-service", "meeting-service", "ai-service", "search-service"):
        root = str(BACKEND_ROOT / service)
        while root in sys.path:
            sys.path.remove(root)
    sys.path[:0] = [str(SEARCH_ROOT), str(BACKEND_ROOT)]


class DeterministicProvider:
    def __init__(self, identity, error=None):
        self.identity = identity
        self.error = error
        self.requests = []

    async def embed(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return importlib.import_module("embeddings.contracts").EmbeddingResponse(
            model_identity=self.identity,
            vectors=[
                [float(sum(text.encode("utf-8")) % 100), 0.2, 0.3]
                for text in request.texts
            ],
        )

    async def aclose(self):
        return None


class FakeEmbeddings:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeOpenAIClient:
    def __init__(self, embeddings):
        self.embeddings = embeddings


class TranscriptIndexingPipelineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _prepare_search_imports()
        self.contracts = importlib.import_module("embeddings.contracts")
        self.errors = importlib.import_module("embeddings.errors")
        self.chunking = importlib.import_module("chunking.transcript_chunker")
        self.chunk_contracts = importlib.import_module("chunking.contracts")
        self.pipeline_module = importlib.import_module("indexing.pipeline")
        self.index_contracts = importlib.import_module("indexing.contracts")
        self.embedding_service_type = importlib.import_module("embeddings.service").EmbeddingService
        self.provider_module = importlib.import_module("embeddings.openai_provider")
        self.transcript_dto_type = importlib.import_module(
            "shared.schemas.transcript"
        ).TranscriptInDB
        self.identity = self.contracts.EmbeddingModelIdentity(
            provider="openai", model="text-embedding-3-small", dimensions=3
        )
        self.scope = self.chunk_contracts.TranscriptIndexScope(
            meeting_id=MEETING_ID,
            transcript_id=TRANSCRIPT_ID,
            owner_id=OWNER_ID,
            organization_id=ORG_ID,
        )
        now = datetime(2026, 10, 3, tzinfo=timezone.utc)
        self.transcript = self.transcript_dto_type(
            id=str(TRANSCRIPT_ID),
            meeting_id=str(MEETING_ID),
            language="en-US",
            segments=[
                {"index": 0, "speaker": "Ada", "text": "Hello team.", "start_ms": 10, "end_ms": 40},
                {"index": 1, "speaker": "Bo", "text": "Ship Friday.", "start_ms": 50, "end_ms": 80},
            ],
            created_at=now,
            updated_at=now,
        )

    def _pipeline(self, *, provider=None, chunker=None):
        adapter = provider or DeterministicProvider(self.identity)
        return (
            self.pipeline_module.TranscriptIndexingPipeline(
                chunker=chunker or self.chunking.TranscriptChunker(max_characters=12),
                embedding_service=self.embedding_service_type(adapter, self.identity),
                embedding_model=self.identity,
            ),
            adapter,
        )

    async def test_empty_transcript_returns_typed_empty_result_without_embedding(self):
        now = datetime(2026, 10, 3, tzinfo=timezone.utc)
        empty = self.transcript_dto_type(
            id=str(TRANSCRIPT_ID), meeting_id=str(MEETING_ID), language="en",
            segments=[], created_at=now, updated_at=now,
        )
        pipeline, provider = self._pipeline()

        result = await pipeline.prepare(empty, scope=self.scope)

        self.assertIsInstance(result, self.index_contracts.TranscriptIndexBatch)
        self.assertTrue(result.is_empty)
        self.assertEqual(result.point_ids, ())
        self.assertEqual(provider.requests, [])

    async def test_single_and_multiple_chunks_preserve_metadata_and_identity(self):
        pipeline, provider = self._pipeline()
        result = await pipeline.prepare(self.transcript, scope=self.scope)

        self.assertEqual(len(result.records), 2)
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(provider.requests[0].texts, ["Hello team.", "Ship Friday."])
        first, second = result.records
        self.assertEqual(first.point_id, self.chunking.transcript_chunk_id(MEETING_ID, TRANSCRIPT_ID, 0))
        self.assertEqual(second.point_id, self.chunking.transcript_chunk_id(MEETING_ID, TRANSCRIPT_ID, 1))
        self.assertEqual((first.chunk.meeting_id, first.chunk.transcript_id), (MEETING_ID, TRANSCRIPT_ID))
        self.assertEqual((first.chunk.owner_id, first.chunk.organization_id), (OWNER_ID, ORG_ID))
        self.assertEqual(first.chunk.text, "Hello team.")
        self.assertEqual(first.chunk.source_segments[0].speaker, "Ada")
        self.assertEqual((first.chunk.start_ms, first.chunk.end_ms), (10, 40))
        self.assertEqual(first.chunk.language, "en-US")
        self.assertEqual(first.embedding_model, self.identity)
        self.assertEqual(first.vector, [float(sum(b"Hello team." ) % 100), 0.2, 0.3])

    async def test_single_chunk_result_has_one_point(self):
        pipeline, _ = self._pipeline(
            chunker=self.chunking.TranscriptChunker(max_characters=100)
        )
        result = await pipeline.prepare(self.transcript, scope=self.scope)
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0].chunk.chunk_index, 0)

    async def test_pipeline_accepts_canonical_normalized_transcript(self):
        normalized = importlib.import_module(
            "shared.transcripts.normalization"
        ).normalize_transcript(self.transcript, meeting_id=MEETING_ID)
        pipeline, _ = self._pipeline(
            chunker=self.chunking.TranscriptChunker(max_characters=100)
        )

        result = await pipeline.prepare(normalized, scope=self.scope)

        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0].chunk.transcript_id, TRANSCRIPT_ID)

    async def test_reordered_provider_indices_are_paired_to_chunk_order(self):
        response = SimpleNamespace(
            data=[
                SimpleNamespace(index=1, embedding=[0.4, 0.5, 0.6]),
                SimpleNamespace(index=0, embedding=[0.1, 0.2, 0.3]),
            ]
        )
        embeddings = FakeEmbeddings(response)
        adapter = self.provider_module.OpenAIEmbeddingProvider(
            api_key=SecretStr("test"), model=self.identity.model, dimensions=3,
            client=FakeOpenAIClient(embeddings),
        )
        pipeline, _ = self._pipeline(provider=adapter)

        result = await pipeline.prepare(self.transcript, scope=self.scope)

        self.assertEqual([record.vector for record in result.records], [
            [0.1, 0.2, 0.3], [0.4, 0.5, 0.6]
        ])
        self.assertEqual([record.chunk.chunk_index for record in result.records], [0, 1])

    async def test_same_inputs_produce_identical_records_for_reindexing(self):
        pipeline, _ = self._pipeline()
        first = await pipeline.prepare(self.transcript, scope=self.scope)
        second = await pipeline.prepare(self.transcript, scope=self.scope)
        self.assertEqual(first, second)
        self.assertEqual(first.point_ids, second.point_ids)

    async def test_duplicate_point_ids_are_rejected_before_embedding(self):
        base_chunker = self.chunking.TranscriptChunker(max_characters=12)

        class DuplicateIdChunker:
            def chunk(self, transcript, *, scope):
                chunks = base_chunker.chunk(transcript, scope=scope)
                return [chunks[0], chunks[1].model_copy(update={"chunk_id": chunks[0].chunk_id})]

        pipeline, provider = self._pipeline(chunker=DuplicateIdChunker())
        with self.assertRaises(self.pipeline_module.DuplicateTranscriptPointIdError):
            await pipeline.prepare(self.transcript, scope=self.scope)
        self.assertEqual(provider.requests, [])

    async def test_ownership_metadata_comes_from_trusted_scope_not_transcript_client_fields(self):
        pipeline, provider = self._pipeline()
        result = await pipeline.prepare(self.transcript, scope=self.scope)
        self.assertEqual(result.records[0].chunk.owner_id, OWNER_ID)
        self.assertEqual(result.records[0].chunk.organization_id, ORG_ID)
        self.assertNotIn("owner_id", self.transcript.model_dump())
        self.assertNotIn("organization_id", self.transcript.model_dump())

        wrong_meeting_scope = self.scope.model_copy(update={"meeting_id": UUID(int=888)})
        with self.assertRaises(self.pipeline_module.TranscriptIndexingInputError):
            await pipeline.prepare(self.transcript, scope=wrong_meeting_scope)
        self.assertEqual(len(provider.requests), 1)

    async def test_dimension_and_nonfinite_mismatches_fail_without_partial_batch(self):
        class InvalidEmbeddingService:
            identity = self.identity

            async def embed_chunks(self, chunks):
                return SimpleNamespace(
                    model_identity=self.identity,
                    vectors=[[float("inf"), 0.2, 0.3], [0.1, 0.2, 0.3]],
                )

        invalid_service = InvalidEmbeddingService()
        pipeline = self.pipeline_module.TranscriptIndexingPipeline(
            chunker=self.chunking.TranscriptChunker(max_characters=12),
            embedding_service=invalid_service,
            embedding_model=self.identity,
        )
        with self.assertRaises(self.errors.MalformedEmbeddingResponseError):
            await pipeline.prepare(self.transcript, scope=self.scope)

        different_identity = self.contracts.EmbeddingModelIdentity(
            provider="openai", model="text-embedding-3-small", dimensions=2
        )

        class WrongDimensionService:
            async def embed_chunks(self, chunks):
                return SimpleNamespace(
                    model_identity=different_identity,
                    vectors=[[0.1, 0.2] for _ in chunks],
                )

        pipeline = self.pipeline_module.TranscriptIndexingPipeline(
            chunker=self.chunking.TranscriptChunker(max_characters=12),
            embedding_service=WrongDimensionService(),
            embedding_model=self.identity,
        )
        with self.assertRaises(self.errors.MalformedEmbeddingResponseError):
            await pipeline.prepare(self.transcript, scope=self.scope)

    async def test_provider_failure_aborts_entire_batch_with_controlled_error(self):
        provider_error = self.errors.EmbeddingProviderUnavailableError()
        pipeline, provider = self._pipeline(
            provider=DeterministicProvider(self.identity, error=provider_error)
        )
        with self.assertRaises(self.errors.EmbeddingProviderUnavailableError):
            await pipeline.prepare(self.transcript, scope=self.scope)
        self.assertEqual(len(provider.requests), 1)

    async def test_index_record_rejects_duplicate_mismatched_or_nonfinite_point_data(self):
        pipeline, _ = self._pipeline(chunker=self.chunking.TranscriptChunker(max_characters=100))
        record = (await pipeline.prepare(self.transcript, scope=self.scope)).records[0]
        with self.assertRaises(ValidationError):
            self.index_contracts.TranscriptIndexRecord(
                point_id=UUID(int=999), chunk=record.chunk,
                embedding_model=self.identity, vector=record.vector,
            )
        with self.assertRaises(ValidationError):
            self.index_contracts.TranscriptIndexRecord(
                point_id=record.point_id, chunk=record.chunk,
                embedding_model=self.identity, vector=[float("nan"), 0.2, 0.3],
            )

    async def test_pipeline_contracts_do_not_import_or_require_qdrant(self):
        script = textwrap.dedent("""
            import sys
            from pathlib import Path
            backend_root, search_root = map(Path, sys.argv[1:])
            sys.path[:0] = [str(search_root), str(backend_root)]
            import indexing.contracts
            import indexing.pipeline
            import chunking.contracts
            import chunking.transcript_chunker
            import app.config.settings
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
