"""Opt-in live Qdrant smoke test; skipped unless explicitly enabled."""

from __future__ import annotations

import importlib
import os
import sys
import unittest
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import SecretStr


class _LazyModels:
    def __getattr__(self, name):
        from qdrant_client import models

        return getattr(models, name)


models = _LazyModels()

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SEARCH_ROOT = BACKEND_ROOT / "search-service"
RUN_QDRANT_INTEGRATION = os.getenv("RUN_QDRANT_INTEGRATION") == "1"


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


@unittest.skipUnless(RUN_QDRANT_INTEGRATION, "Set RUN_QDRANT_INTEGRATION=1 for live Qdrant")
class QdrantLiveIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        _prepare_search_imports()
        settings_module = importlib.import_module("app.config.settings")
        self.settings = settings_module.SearchSettings(
            _env_file=None,
            qdrant_url=os.getenv("QDRANT_INTEGRATION_URL", "http://localhost:6333"),
            qdrant_api_key=(
                SecretStr(os.environ["QDRANT_API_KEY"])
                if os.getenv("QDRANT_API_KEY") else None
            ),
            qdrant_collection_name=f"phase104_{uuid4().hex}",
            embedding_provider="openai",
            embedding_model="phase104-test-model",
            embedding_dimensions=3,
        )
        self.repository_module = importlib.import_module("vectorstore.qdrant_store")
        self.repository = self.repository_module.QdrantVectorRepository(self.settings)
        self.meeting_id = uuid4()
        self.transcript_id = uuid4()

    async def asyncTearDown(self) -> None:
        if hasattr(self, "repository"):
            try:
                # Each test gets a unique collection name; cleanup is limited
                # to resources owned by this test, never the app collection.
                if self.repository._initialized:
                    await self.repository._client.delete_collection(
                        self.settings.qdrant_collection_name
                    )
            finally:
                await self.repository.aclose()

    async def test_collection_upsert_and_transcript_deletion_against_live_server(self):
        chunk_contracts = importlib.import_module("chunking.contracts")
        index_contracts = importlib.import_module("indexing.contracts")
        embedding_contracts = importlib.import_module("embeddings.contracts")
        chunk_id = importlib.import_module("chunking.transcript_chunker").transcript_chunk_id(
            self.meeting_id, self.transcript_id, 0
        )
        chunk = chunk_contracts.TranscriptChunk(
            chunk_id=chunk_id,
            meeting_id=self.meeting_id,
            transcript_id=self.transcript_id,
            owner_id=uuid4(),
            organization_id=uuid4(),
            chunk_index=0,
            source_segments=[{"index": 0}],
            text="Live integration fixture",
        )
        identity = embedding_contracts.EmbeddingModelIdentity(
            provider="openai", model=self.settings.embedding_model, dimensions=3
        )
        batch = index_contracts.TranscriptIndexBatch(
            meeting_id=self.meeting_id,
            transcript_id=self.transcript_id,
            records=[index_contracts.TranscriptIndexRecord(
                point_id=chunk_id, chunk=chunk, embedding_model=identity,
                vector=[0.1, 0.2, 0.3],
            )],
        )

        await self.repository.initialize_collection()
        await self.repository.upsert_transcript_batch(batch)
        count = await self.repository._client.count(
            collection_name=self.settings.qdrant_collection_name,
            count_filter=models.Filter(must=[models.FieldCondition(
                key="transcript_id", match=models.MatchValue(value=str(self.transcript_id))
            )]),
            exact=True,
        )
        self.assertEqual(count.count, 1)

        await self.repository.delete_transcript(self.transcript_id)
        count = await self.repository._client.count(
            collection_name=self.settings.qdrant_collection_name,
            count_filter=models.Filter(must=[models.FieldCondition(
                key="transcript_id", match=models.MatchValue(value=str(self.transcript_id))
            )]),
            exact=True,
        )
        self.assertEqual(count.count, 0)

    async def test_similarity_search_isolated_to_authorized_owner(self):
        chunk_contracts = importlib.import_module("chunking.contracts")
        chunker = importlib.import_module("chunking.transcript_chunker")
        index_contracts = importlib.import_module("indexing.contracts")
        embedding_contracts = importlib.import_module("embeddings.contracts")
        scope_contract = importlib.import_module("retrieval.contracts")

        owner_a = uuid4()
        owner_b = uuid4()
        owner_without_points = uuid4()
        embedding_model = embedding_contracts.EmbeddingModelIdentity(
            provider=self.settings.embedding_provider,
            model=self.settings.embedding_model,
            dimensions=self.settings.embedding_dimensions,
        )

        def make_batch(owner_id, vector, text):
            meeting_id = uuid4()
            transcript_id = uuid4()
            chunk_id = chunker.transcript_chunk_id(meeting_id, transcript_id, 0)
            chunk = chunk_contracts.TranscriptChunk(
                chunk_id=chunk_id,
                meeting_id=meeting_id,
                transcript_id=transcript_id,
                owner_id=owner_id,
                organization_id=uuid4(),
                chunk_index=0,
                source_segments=[{"index": 0}],
                language="en",
                text=text,
            )
            record = index_contracts.TranscriptIndexRecord(
                point_id=chunk_id,
                chunk=chunk,
                embedding_model=embedding_model,
                vector=vector,
            )
            return index_contracts.TranscriptIndexBatch(
                meeting_id=meeting_id,
                transcript_id=transcript_id,
                records=[record],
            ), chunk_id

        # The configured test collection uses three-dimensional cosine vectors.
        # Orthogonal A vectors make the nearest expected point unambiguous.
        query = [1.0, 0.0, 0.0]
        batch_a_nearest, point_a_nearest = make_batch(
            owner_a, [1.0, 0.0, 0.0], "Owner A nearest fixture"
        )
        batch_a_other, point_a_other = make_batch(
            owner_a, [0.0, 1.0, 0.0], "Owner A second fixture"
        )
        batch_b, point_b = make_batch(
            owner_b, [0.8, 0.6, 0.0], "Owner B fixture"
        )

        await self.repository.initialize_collection()
        for batch in (batch_a_nearest, batch_a_other, batch_b):
            await self.repository.upsert_transcript_batch(batch)

        results_a = await self.repository.search(
            query,
            scope=scope_contract.SearchAuthorizationScope(owner_id=owner_a),
            top_k=10,
        )
        result_ids_a = {result.chunk_id for result in results_a}
        self.assertIn(point_a_nearest, result_ids_a)
        self.assertIn(point_a_other, result_ids_a)
        self.assertNotIn(point_b, result_ids_a)
        self.assertEqual(
            [result.chunk_id for result in results_a],
            [point_a_nearest, point_a_other],
        )
        self.assertAlmostEqual(results_a[0].score, 1.0)
        self.assertAlmostEqual(results_a[1].score, 0.0)

        results_b = await self.repository.search(
            query,
            scope=scope_contract.SearchAuthorizationScope(owner_id=owner_b),
            top_k=10,
        )
        result_ids_b = {result.chunk_id for result in results_b}
        self.assertEqual(result_ids_b, {point_b})
        self.assertNotIn(point_a_nearest, result_ids_b)
        self.assertNotIn(point_a_other, result_ids_b)

        results_without_points = await self.repository.search(
            query,
            scope=scope_contract.SearchAuthorizationScope(
                owner_id=owner_without_points
            ),
            top_k=10,
        )
        self.assertEqual(results_without_points, [])


if __name__ == "__main__":
    unittest.main()
