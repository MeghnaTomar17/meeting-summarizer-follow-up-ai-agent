"""Sanitized model execution failure categories."""

from __future__ import annotations


class ModelExecutionError(Exception):
    """Base failure safe to pass within the AI Service boundary."""

    safe_message = "Model execution failed."

    def __init__(self) -> None:
        super().__init__(self.safe_message)


class ProviderNotConfiguredError(ModelExecutionError):
    safe_message = "No model provider is configured."


class ModelProviderUnavailableError(ModelExecutionError):
    safe_message = "The model provider is unavailable."


class ModelTimeoutError(ModelExecutionError):
    safe_message = "The model request timed out."


class MalformedModelOutputError(ModelExecutionError):
    safe_message = "The model returned output that did not match the required structure."


class ModelRequestRejectedError(ModelExecutionError):
    safe_message = "The model provider rejected the request."


class UnexpectedModelProviderError(ModelExecutionError):
    safe_message = "The model provider failed unexpectedly."


__all__ = [
    "MalformedModelOutputError",
    "ModelExecutionError",
    "ModelProviderUnavailableError",
    "ModelRequestRejectedError",
    "ModelTimeoutError",
    "ProviderNotConfiguredError",
    "UnexpectedModelProviderError",
]
