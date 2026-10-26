"""Search-owned Qdrant persistence repository; contains no auth or ORM code."""

from __future__ import annotations

import math
import logging
from collections.abc import Mapping
from typing import Any, Protocol
from uuid import UUID

from chunking.contracts import TranscriptChunk
from chunking.transcript_chunker import transcript_chunk_id
from embeddings.contracts import EmbeddingModelIdentity
from pydantic import ValidationError

from app.config.settings import SearchSettings, get_settings
from indexing.contracts import TranscriptIndexBatch
from retrieval.contracts import (
    MAX_SEMANTIC_SEARCH_TOP_K,
    SearchAuthorizationScope,
    SemanticSearchResult,
)
from vectorstore.errors import (
    QdrantCollectionConfigurationMismatchError,
    QdrantInvalidIndexBatchError,
    QdrantInvalidQueryError,
    QdrantMalformedSearchResultError,
    QdrantOperationError,
    QdrantRepositoryNotInitializedError,
)


class QdrantClientPort(Protocol):
    """Small async client boundary implemented by Qdrant and test fakes."""

    async def collection_exists(self, collection_name: str) -> bool: ...

    async def get_collection(self, collection_name: str) -> Any: ...

    async def create_collection(
        self, *, collection_name: str, vectors_config: Any
    ) -> Any: ...

    async def scroll(self, collection_name: str, **kwargs: Any) -> Any: ...

    async def upsert(self, collection_name: str, *, points: Any, wait: bool = True) -> Any: ...

    async def delete(self, collection_name: str, *, points_selector: Any, wait: bool = True) -> Any: ...

    async def query_points(self, collection_name: str, **kwargs: Any) -> Any: ...

    async def close(self) -> None: ...


def _qdrant_models() -> Any:
    """Load the SDK only when a Qdrant operation is actually requested."""
    from qdrant_client import models

    return models


def AsyncQdrantClient(**kwargs: Any) -> Any:
    """Construct the SDK client lazily, keeping Search contracts lightweight."""
    from qdrant_client import AsyncQdrantClient as QdrantAsyncClient

    return QdrantAsyncClient(**kwargs)


def _distance_for(setting: str) -> Any:
    models = _qdrant_models()
    return {
        "Cosine": models.Distance.COSINE,
        "Dot": models.Distance.DOT,
        "Euclid": models.Distance.EUCLID,
    }[setting]
_SCROLL_PAGE_SIZE = 256
_logger = logging.getLogger(__name__)


class QdrantVectorRepository:
    """Persist complete prepared transcript batches as Qdrant points.

    Collection creation is explicit through :meth:`initialize_collection`.
    Transcript replacement upserts the desired points first and then removes
    stale points; these operations are not an atomic transaction.
    """

    def __init__(
        self,
        settings: SearchSettings | None = None,
        *,
        client: QdrantClientPort | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._owns_client = client is None
        if client is None:
            try:
                api_key = self._settings.qdrant_api_key
                self._client: QdrantClientPort = AsyncQdrantClient(
                    url=self._settings.qdrant_url,
                    api_key=api_key.get_secret_value() if api_key is not None else None,
                    timeout=self._settings.qdrant_timeout_seconds,
                )
            except Exception:
                raise QdrantOperationError() from None
        else:
            self._client = client
        self._initialized = False

    async def initialize_collection(self) -> None:
        """Create the configured collection if absent; never recreate mismatch."""
        collection_name = self._settings.qdrant_collection_name
        try:
            if await self._client.collection_exists(collection_name):
                collection = await self._client.get_collection(collection_name)
                self._validate_existing_collection(collection)
            else:
                await self._client.create_collection(
                    collection_name=collection_name,
                    vectors_config=_qdrant_models().VectorParams(
                        size=self._settings.embedding_dimensions,
                        distance=_distance_for(self._settings.qdrant_distance_metric),
                    ),
                )
            self._initialized = True
        except QdrantCollectionConfigurationMismatchError:
            raise
        except Exception:
            raise QdrantOperationError() from None

    async def upsert_transcript_batch(self, batch: TranscriptIndexBatch) -> None:
        """Replace one transcript's desired point set, then prune stale IDs.

        If the desired upsert fails, stale deletion is not attempted. If the
        upsert succeeds but stale deletion fails, the new points and old stale
        points may coexist until a retry. Qdrant writes are idempotent by the
        established deterministic point ID, but this method is not atomic.
        """
        self._require_initialized()
        self._validate_batch(batch)

        existing_ids = await self._scroll_transcript_point_ids(batch.transcript_id)
        desired_ids = {str(record.point_id) for record in batch.records}
        stale_ids = existing_ids - desired_ids

        if batch.records:
            models = _qdrant_models()
            points = [
                models.PointStruct(
                    id=str(record.point_id),
                    vector=record.vector,
                    payload={
                        **record.chunk.model_dump(mode="json"),
                        "embedding_model": record.embedding_model.model_dump(mode="json"),
                    },
                )
                for record in batch.records
            ]
            try:
                await self._client.upsert(
                    collection_name=self._settings.qdrant_collection_name,
                    points=points,
                    wait=True,
                )
            except Exception:
                raise QdrantOperationError() from None

        if stale_ids:
            try:
                await self._client.delete(
                    collection_name=self._settings.qdrant_collection_name,
                    points_selector=_qdrant_models().PointIdsList(
                        points=sorted(stale_ids)
                    ),
                    wait=True,
                )
            except Exception:
                raise QdrantOperationError() from None

    async def search(
        self,
        query_vector: list[float],
        *,
        scope: SearchAuthorizationScope,
        top_k: int,
        meeting_ids: list[UUID] | None = None,
    ) -> list[SemanticSearchResult]:
        """Search only within the required verified owner scope."""
        if (
            isinstance(top_k, bool)
            or not isinstance(top_k, int)
            or not 1 <= top_k <= MAX_SEMANTIC_SEARCH_TOP_K
            or not isinstance(query_vector, list)
            or len(query_vector) != self._settings.embedding_dimensions
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in query_vector
            )
        ):
            raise QdrantInvalidQueryError()

        try:
            collection = await self._client.get_collection(
                self._settings.qdrant_collection_name
            )
            self._validate_existing_collection(collection)
            response = await self._client.query_points(
                collection_name=self._settings.qdrant_collection_name,
                query=query_vector,
                query_filter=self._search_filter(scope.owner_id, meeting_ids),
                limit=top_k,
                with_payload=True,
                with_vectors=False,
            )
        except QdrantCollectionConfigurationMismatchError:
            raise
        except Exception:
            raise QdrantOperationError() from None

        points = getattr(response, "points", None)
        if not isinstance(points, list) or len(points) > top_k:
            raise QdrantMalformedSearchResultError()

        results: list[SemanticSearchResult] = []
        for point in points:
            results.append(self._validate_search_point(point, scope))
        return results

    async def delete_transcript(self, transcript_id: UUID) -> None:
        """Delete points matching a transcript payload identity."""
        await self._delete_by_payload("transcript_id", transcript_id)

    async def delete_meeting(self, meeting_id: UUID) -> None:
        """Delete points matching a meeting payload identity."""
        await self._delete_by_payload("meeting_id", meeting_id)

    async def aclose(self) -> None:
        """Close only the SDK client owned by this repository."""
        if self._owns_client:
            try:
                await self._client.close()
            except Exception:
                raise QdrantOperationError() from None
        self._initialized = False

    async def _scroll_transcript_point_ids(self, transcript_id: UUID) -> set[str]:
        selector = self._payload_filter("transcript_id", transcript_id)
        point_ids: set[str] = set()
        offset: Any = None
        try:
            while True:
                points, offset = await self._client.scroll(
                    collection_name=self._settings.qdrant_collection_name,
                    scroll_filter=selector,
                    limit=_SCROLL_PAGE_SIZE,
                    offset=offset,
                    with_payload=False,
                    with_vectors=False,
                )
                point_ids.update(str(point.id) for point in points)
                if offset is None:
                    return point_ids
        except Exception:
            raise QdrantOperationError() from None

    async def _delete_by_payload(self, field: str, value: UUID) -> None:
        self._require_initialized()
        try:
            await self._client.delete(
                collection_name=self._settings.qdrant_collection_name,
                points_selector=_qdrant_models().FilterSelector(
                    filter=self._payload_filter(field, value)
                ),
                wait=True,
            )
        except Exception:
            raise QdrantOperationError() from None

    @staticmethod
    def _payload_filter(field: str, value: UUID) -> Any:
        models = _qdrant_models()
        return models.Filter(
            must=[
                models.FieldCondition(
                    key=field,
                    match=models.MatchValue(value=str(value)),
                )
            ]
        )

    @staticmethod
    def _search_filter(owner_id: UUID, meeting_ids: list[UUID] | None) -> Any:
        models = _qdrant_models()
        conditions = [
            models.FieldCondition(
                key="owner_id", match=models.MatchValue(value=str(owner_id))
            )
        ]
        if meeting_ids is not None:
            conditions.append(models.FieldCondition(
                key="meeting_id",
                match=models.MatchAny(any=[str(meeting_id) for meeting_id in meeting_ids]),
            ))
        return models.Filter(must=conditions)

    def _validate_batch(self, batch: TranscriptIndexBatch) -> None:
        try:
            validated = TranscriptIndexBatch.model_validate(batch.model_dump())
        except ValidationError:
            raise QdrantInvalidIndexBatchError() from None
        if validated != batch:
            raise QdrantInvalidIndexBatchError()
        point_ids = [record.point_id for record in batch.records]
        if len(point_ids) != len(set(point_ids)):
            raise QdrantInvalidIndexBatchError()
        for record in batch.records:
            if (
                record.embedding_model.dimensions != self._settings.embedding_dimensions
                or record.embedding_model.provider != self._settings.embedding_provider
                or record.embedding_model.model != self._settings.embedding_model
            ):
                raise QdrantInvalidIndexBatchError()

    def _validate_search_point(
        self, point: Any, scope: SearchAuthorizationScope
    ) -> SemanticSearchResult:
        try:
            payload = point.payload
            if not isinstance(payload, dict):
                raise ValueError("Missing payload")
            chunk = TranscriptChunk.model_validate(
                {
                    field_name: payload[field_name]
                    for field_name in TranscriptChunk.model_fields
                }
            )
            model_identity = EmbeddingModelIdentity.model_validate(
                payload["embedding_model"]
            )
            point_id = UUID(str(point.id))
            expected_id = transcript_chunk_id(
                chunk.meeting_id, chunk.transcript_id, chunk.chunk_index
            )
            if (
                point_id != chunk.chunk_id
                or point_id != expected_id
                or chunk.owner_id != scope.owner_id
                or model_identity.provider != self._settings.embedding_provider
                or model_identity.model != self._settings.embedding_model
                or model_identity.dimensions != self._settings.embedding_dimensions
            ):
                raise ValueError("Inconsistent point identity or owner")
            score = point.score
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                raise ValueError("Invalid similarity score")
            return SemanticSearchResult(
                meeting_id=chunk.meeting_id,
                transcript_id=chunk.transcript_id,
                chunk_id=chunk.chunk_id,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                language=chunk.language,
                source_segments=[
                    segment.model_dump() for segment in chunk.source_segments
                ],
                start_ms=chunk.start_ms,
                end_ms=chunk.end_ms,
                score=score,
            )
        except Exception as error:
            if isinstance(error, ValidationError):
                validation_summary = ",".join(
                    f"{'.'.join(str(part) for part in item['loc'])}:{item['type']}"
                    for item in error.errors(include_input=False)
                )
            else:
                validation_summary = type(error).__name__
            _logger.error(
                "qdrant_search_result_validation_failed validation=%s",
                validation_summary,
            )
            raise QdrantMalformedSearchResultError() from None

    def _validate_existing_collection(self, collection: Any) -> None:
        try:
            vectors = collection.config.params.vectors
            if isinstance(vectors, Mapping):
                raise ValueError("Named-vector collections are not supported")
            size = vectors.size
            distance = vectors.distance
        except Exception:
            raise QdrantCollectionConfigurationMismatchError() from None
        if (
            size != self._settings.embedding_dimensions
            or distance != _distance_for(self._settings.qdrant_distance_metric)
        ):
            raise QdrantCollectionConfigurationMismatchError()

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise QdrantRepositoryNotInitializedError()


__all__ = ["QdrantClientPort", "QdrantVectorRepository"]
