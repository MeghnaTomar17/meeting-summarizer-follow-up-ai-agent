"""Sanitized failures for Search Service Qdrant persistence operations."""

from __future__ import annotations


class QdrantRepositoryError(Exception):
    """Base controlled error; never includes a raw client exception."""

    safe_message = "Vector persistence failed."

    def __init__(self) -> None:
        super().__init__(self.safe_message)


class QdrantCollectionConfigurationMismatchError(QdrantRepositoryError):
    safe_message = "Qdrant collection configuration does not match Search settings."


class QdrantRepositoryNotInitializedError(QdrantRepositoryError):
    safe_message = "Qdrant collection has not been initialized."


class QdrantInvalidIndexBatchError(QdrantRepositoryError):
    safe_message = "Transcript index batch does not match Qdrant configuration."


class QdrantOperationError(QdrantRepositoryError):
    safe_message = "Qdrant operation failed."


class QdrantMalformedSearchResultError(QdrantRepositoryError):
    safe_message = "Qdrant returned an invalid search result."


class QdrantInvalidQueryError(QdrantRepositoryError):
    safe_message = "Semantic search query is incompatible with Qdrant settings."


__all__ = [
    "QdrantRepositoryError",
    "QdrantCollectionConfigurationMismatchError",
    "QdrantRepositoryNotInitializedError",
    "QdrantInvalidIndexBatchError",
    "QdrantOperationError",
    "QdrantMalformedSearchResultError",
    "QdrantInvalidQueryError",
]
