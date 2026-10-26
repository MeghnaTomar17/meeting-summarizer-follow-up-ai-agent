"""Sanitized failure categories for the Search Service embedding boundary."""

from __future__ import annotations


class EmbeddingExecutionError(Exception):
    """Base embedding failure with a safe, provider-independent message."""

    safe_message = "Embedding generation failed."

    def __init__(self) -> None:
        super().__init__(self.safe_message)


class EmbeddingProviderNotConfiguredError(EmbeddingExecutionError):
    safe_message = "No embedding provider is configured."


class EmbeddingProviderUnavailableError(EmbeddingExecutionError):
    safe_message = "The embedding provider is unavailable."


class EmbeddingTimeoutError(EmbeddingExecutionError):
    safe_message = "The embedding request timed out."


class EmbeddingRequestRejectedError(EmbeddingExecutionError):
    safe_message = "The embedding provider rejected the request."


class MalformedEmbeddingResponseError(EmbeddingExecutionError):
    safe_message = "The embedding provider returned an invalid response."


class UnexpectedEmbeddingProviderError(EmbeddingExecutionError):
    safe_message = "The embedding provider failed unexpectedly."


__all__ = [
    "EmbeddingExecutionError",
    "EmbeddingProviderNotConfiguredError",
    "EmbeddingProviderUnavailableError",
    "EmbeddingTimeoutError",
    "EmbeddingRequestRejectedError",
    "MalformedEmbeddingResponseError",
    "UnexpectedEmbeddingProviderError",
]
