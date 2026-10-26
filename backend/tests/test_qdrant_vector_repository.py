"""Qdrant persistence tests using a deterministic fake client boundary."""

from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from pydantic import SecretStr


class _LazyModels:
    def __getattr__(self, name):
        from qdrant_client import models

        return getattr(models, name)


models = _LazyModels()

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


class FakePoint:
    def __init__(self, point_id, payload):
        self.id = str(point_id)
        self.payload = payload


class FakeQdrantClient:
    def __init__(self, *, existing_collection=None):
        self.collection = existing_collection
        self.points: dict[str, FakePoint] = {}
        self.calls: list[tuple] = []
        self.fail_upsert = False
        self.fail_delete = False
        self.close_count = 0

    async def collection_exists(self, collection_name):
        self.calls.append(("collection_exists", collection_name))
        return self.collection is not None

    async def get_collection(self, collection_name):
        self.calls.append(("get_collection", collection_name))
        return self.collection

    async def create_collection(self, *, collection_name, vectors_config):
        self.calls.append(("create_collection", collection_name, vectors_config))
        self.collection = SimpleNamespace(
            config=SimpleNamespace(
                params=SimpleNamespace(vectors=vectors_config)
            )
        )

    async def scroll(self, collection_name, **kwargs):
        self.calls.append(("scroll", collection_name, kwargs))
        point_filter = kwargs["scroll_filter"]
        condition = point_filter.must[0]
        target = condition.match.value
        matching = [
            point for point in self.points.values()
            if point.payload.get(condition.key) == target
        ]
        offset = kwargs.get("offset") or 0
        limit = kwargs["limit"]
        page = matching[offset:offset + limit]
        next_offset = offset + limit if offset + limit < len(matching) else None
        return page, next_offset

    async def upsert(self, collection_name, *, points, wait=True):
        self.calls.append(("upsert", collection_name, list(points), wait))
        if self.fail_upsert:
            raise RuntimeError("qdrant token=private-secret upsert failed")
        for point in points:
            self.points[str(point.id)] = FakePoint(point.id, point.payload)

    async def delete(self, collection_name, *, points_selector, wait=True):
        self.calls.append(("delete", collection_name, points_selector, wait))
        if self.fail_delete:
            raise RuntimeError("qdrant token=private-secret delete failed")
        if isinstance(points_selector, models.PointIdsList):
            targets = {str(point_id) for point_id in points_selector.points}
        else:
            condition = points_selector.filter.must[0]
            targets = {
                point_id for point_id, point in self.points.items()
                if point.payload.get(condition.key) == condition.match.value
            }
        for point_id in targets:
            self.points.pop(point_id, None)

    async def close(self):
        self.close_count += 1


class QdrantVectorRepositoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _prepare_search_imports()
        self.settings_type = importlib.import_module("app.config.settings").SearchSettings
        self.repository_module = importlib.import_module("vectorstore.qdrant_store")
        self.errors = importlib.import_module("vectorstore.errors")
        self.chunk_contracts = importlib.import_module("chunking.contracts")
        self.index_contracts = importlib.import_module("indexing.contracts")
        self.chunk_ids = importlib.import_module("chunking.transcript_chunker").transcript_chunk_id
        self.settings = self.settings_type(
            _env_file=None,
            qdrant_url="https://vectors.example.test",
            qdrant_api_key=SecretStr("qdrant-test-secret"),
            qdrant_collection_name="test_meeting_chunks",
            qdrant_timeout_seconds=7,
            embedding_provider="openai",
            embedding_model="text-embedding-3-small",
            embedding_dimensions=3,
            qdrant_distance_metric="Cosine",
        )
        self.repository_error = self.errors.QdrantRepositoryError

    def _chunk_and_record(self, chunk_index: int, *, transcript_id=TRANSCRIPT_ID):
        chunk_id = self.chunk_ids(MEETING_ID, transcript_id, chunk_index)
        chunk = self.chunk_contracts.TranscriptChunk(
            chunk_id=chunk_id,
            meeting_id=MEETING_ID,
            transcript_id=transcript_id,
            owner_id=OWNER_ID,
            organization_id=ORG_ID,
            chunk_index=chunk_index,
            source_segments=[
                {"index": chunk_index, "speaker": "Ada", "start_ms": 10, "end_ms": 20}
            ],
            start_ms=10,
            end_ms=20,
            language="en-US",
            text=f"chunk text {chunk_index}",
        )
        identity = importlib.import_module("embeddings.contracts").EmbeddingModelIdentity(
            provider="openai", model="text-embedding-3-small", dimensions=3
        )
        return self.index_contracts.TranscriptIndexRecord(
            point_id=chunk_id,
            chunk=chunk,
            embedding_model=identity,
            vector=[float(chunk_index), 0.2, 0.3],
        )

    def _batch(self, count=2, *, transcript_id=TRANSCRIPT_ID):
        return self.index_contracts.TranscriptIndexBatch(
            meeting_id=MEETING_ID,
            transcript_id=transcript_id,
            records=[
                self._chunk_and_record(index, transcript_id=transcript_id)
                for index in range(count)
            ],
        )

    async def _initialized_repository(self, client=None):
        client = client or FakeQdrantClient()
        repository = self.repository_module.QdrantVectorRepository(
            self.settings, client=client
        )
        await repository.initialize_collection()
        return repository, client

    async def test_collection_created_with_configured_name_dimensions_and_distance(self):
        repository, client = await self._initialized_repository()
        created = [call for call in client.calls if call[0] == "create_collection"]
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0][1], "test_meeting_chunks")
        self.assertEqual(created[0][2].size, 3)
        self.assertEqual(created[0][2].distance, models.Distance.COSINE)
        with self.assertRaises(self.errors.QdrantRepositoryNotInitializedError):
            repository._initialized = False
            await repository.upsert_transcript_batch(self._batch())

    async def test_existing_matching_collection_is_reused_without_recreation(self):
        client = FakeQdrantClient(existing_collection=SimpleNamespace(
            config=SimpleNamespace(params=SimpleNamespace(vectors=models.VectorParams(
                size=3, distance=models.Distance.COSINE
            )))
        ))
        repository = self.repository_module.QdrantVectorRepository(self.settings, client=client)
        await repository.initialize_collection()
        self.assertFalse(any(call[0] == "create_collection" for call in client.calls))

    async def test_collection_dimension_or_distance_mismatch_is_controlled_no_recreate(self):
        client = FakeQdrantClient(existing_collection=SimpleNamespace(
            config=SimpleNamespace(params=SimpleNamespace(vectors=models.VectorParams(
                size=99, distance=models.Distance.DOT
            )))
        ))
        repository = self.repository_module.QdrantVectorRepository(self.settings, client=client)
        with self.assertRaises(self.errors.QdrantCollectionConfigurationMismatchError):
            await repository.initialize_collection()
        self.assertFalse(any(call[0] == "create_collection" for call in client.calls))

    async def test_successful_upsert_preserves_id_vector_payload_and_embedding_identity(self):
        repository, client = await self._initialized_repository()
        batch = self._batch(1)

        await repository.upsert_transcript_batch(batch)

        record = batch.records[0]
        stored = client.points[str(record.point_id)]
        self.assertEqual(stored.id, str(record.point_id))
        self.assertEqual(stored.payload["chunk_id"], str(record.chunk.chunk_id))
        self.assertEqual(stored.payload["meeting_id"], str(MEETING_ID))
        self.assertEqual(stored.payload["transcript_id"], str(TRANSCRIPT_ID))
        self.assertEqual(stored.payload["owner_id"], str(OWNER_ID))
        self.assertEqual(stored.payload["organization_id"], str(ORG_ID))
        self.assertEqual(stored.payload["source_segments"][0]["speaker"], "Ada")
        self.assertEqual(stored.payload["embedding_model"], {
            "provider": "openai", "model": "text-embedding-3-small", "dimensions": 3
        })
        upsert = next(call for call in client.calls if call[0] == "upsert")
        self.assertEqual(upsert[2][0].vector, record.vector)

    async def test_record_dimension_or_model_mismatch_fails_before_qdrant_scroll(self):
        repository, client = await self._initialized_repository()
        batch = self._batch(1)
        wrong_identity = importlib.import_module("embeddings.contracts").EmbeddingModelIdentity(
            provider="openai", model="another-model", dimensions=3
        )
        record = batch.records[0].model_copy(update={"embedding_model": wrong_identity})
        bad_batch = batch.model_copy(update={"records": [record]})

        with self.assertRaises(self.errors.QdrantInvalidIndexBatchError):
            await repository.upsert_transcript_batch(bad_batch)
        self.assertFalse(any(call[0] == "scroll" for call in client.calls))

    async def test_transcript_replacement_upserts_then_deletes_only_stale_ids(self):
        repository, client = await self._initialized_repository()
        desired = self._batch(2)
        stale_id = str(self.chunk_ids(MEETING_ID, TRANSCRIPT_ID, 2))
        client.points[stale_id] = FakePoint(stale_id, {"transcript_id": str(TRANSCRIPT_ID)})

        await repository.upsert_transcript_batch(desired)

        self.assertEqual(set(client.points), {str(record.point_id) for record in desired.records})
        operation_names = [call[0] for call in client.calls]
        self.assertLess(operation_names.index("scroll"), operation_names.index("upsert"))
        self.assertLess(operation_names.index("upsert"), operation_names.index("delete"))

    async def test_empty_transcript_batch_prunes_all_existing_transcript_points(self):
        repository, client = await self._initialized_repository()
        await repository.upsert_transcript_batch(self._batch(2))
        prior_upsert_count = sum(call[0] == "upsert" for call in client.calls)
        empty = self.index_contracts.TranscriptIndexBatch(
            meeting_id=MEETING_ID, transcript_id=TRANSCRIPT_ID, records=[]
        )

        await repository.upsert_transcript_batch(empty)

        self.assertEqual(client.points, {})
        self.assertEqual(
            sum(call[0] == "upsert" for call in client.calls), prior_upsert_count
        )

    async def test_meeting_and_transcript_deletion_use_payload_filters(self):
        repository, client = await self._initialized_repository()
        await repository.upsert_transcript_batch(self._batch(2))
        other_transcript = UUID("084c3a14-1a7f-41c9-a7c8-1e195aa5313b")
        await repository.upsert_transcript_batch(
            self._batch(1, transcript_id=other_transcript)
        )

        await repository.delete_transcript(TRANSCRIPT_ID)
        self.assertEqual(len(client.points), 1)
        delete_call = next(call for call in reversed(client.calls) if call[0] == "delete")
        self.assertIsInstance(delete_call[2], models.FilterSelector)
        self.assertEqual(delete_call[2].filter.must[0].key, "transcript_id")

        await repository.delete_meeting(MEETING_ID)
        self.assertEqual(client.points, {})
        delete_calls = [call for call in client.calls if call[0] == "delete"]
        self.assertEqual(delete_calls[-1][2].filter.must[0].key, "meeting_id")

    async def test_repeated_identical_batch_is_idempotent_by_deterministic_ids(self):
        repository, client = await self._initialized_repository()
        batch = self._batch(2)
        await repository.upsert_transcript_batch(batch)
        first_point_ids = set(client.points)

        await repository.upsert_transcript_batch(batch)

        self.assertEqual(set(client.points), first_point_ids)
        upserts = [call for call in client.calls if call[0] == "upsert"]
        self.assertEqual([str(point.id) for point in upserts[0][2]],
                         [str(point.id) for point in upserts[1][2]])

    async def test_upsert_failure_does_not_attempt_stale_deletion_and_is_sanitized(self):
        repository, client = await self._initialized_repository()
        stale_id = str(self.chunk_ids(MEETING_ID, TRANSCRIPT_ID, 3))
        client.points[stale_id] = FakePoint(stale_id, {"transcript_id": str(TRANSCRIPT_ID)})
        client.fail_upsert = True

        with self.assertRaises(self.errors.QdrantOperationError) as raised:
            await repository.upsert_transcript_batch(self._batch(1))

        self.assertNotIn("private-secret", str(raised.exception))
        self.assertIn(stale_id, client.points)
        self.assertFalse(any(call[0] == "delete" for call in client.calls))

    async def test_stale_delete_failure_leaves_new_and_old_points_for_retry(self):
        repository, client = await self._initialized_repository()
        stale_id = str(self.chunk_ids(MEETING_ID, TRANSCRIPT_ID, 4))
        client.points[stale_id] = FakePoint(stale_id, {"transcript_id": str(TRANSCRIPT_ID)})
        batch = self._batch(1)
        client.fail_delete = True

        with self.assertRaises(self.errors.QdrantOperationError):
            await repository.upsert_transcript_batch(batch)
        self.assertIn(stale_id, client.points)
        self.assertIn(str(batch.records[0].point_id), client.points)

        client.fail_delete = False
        await repository.upsert_transcript_batch(batch)
        self.assertEqual(set(client.points), {str(batch.records[0].point_id)})

    async def test_credentials_are_secret_and_client_failures_do_not_leak_details(self):
        client = FakeQdrantClient()
        constructor_args = {}

        def fake_client(**kwargs):
            constructor_args.update(kwargs)
            return client

        repository_module = self.repository_module
        with patch.object(repository_module, "AsyncQdrantClient", side_effect=fake_client):
            repository = repository_module.QdrantVectorRepository(self.settings)
        self.assertEqual(constructor_args["api_key"], "qdrant-test-secret")
        self.assertEqual(constructor_args["timeout"], 7)
        self.assertNotIn("qdrant-test-secret", repr(self.settings))
        client.fail_upsert = True
        await repository.initialize_collection()
        with self.assertRaises(self.errors.QdrantOperationError) as raised:
            await repository.upsert_transcript_batch(self._batch(1))
        self.assertNotIn("private-secret", str(raised.exception))
        self.assertNotIn("qdrant-test-secret", repr(raised.exception))

    async def test_scroll_pages_are_all_considered_for_stale_point_removal(self):
        repository, client = await self._initialized_repository()
        for index in range(300):
            point_id = str(self.chunk_ids(MEETING_ID, TRANSCRIPT_ID, index))
            client.points[point_id] = FakePoint(point_id, {"transcript_id": str(TRANSCRIPT_ID)})
        empty = self.index_contracts.TranscriptIndexBatch(
            meeting_id=MEETING_ID, transcript_id=TRANSCRIPT_ID, records=[]
        )

        await repository.upsert_transcript_batch(empty)

        self.assertEqual(client.points, {})
        scrolls = [call for call in client.calls if call[0] == "scroll"]
        self.assertEqual(len(scrolls), 2)


if __name__ == "__main__":
    unittest.main()
