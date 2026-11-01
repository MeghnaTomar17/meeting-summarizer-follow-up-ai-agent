"""Exact provider/model metadata used by the AI request boundary.

Only the explicitly registered identifier is supported. Published architecture
metadata is kept separate from an application's effective runtime context; the
latter is intentionally unknown until Ollama configuration is verified.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


OLLAMA_PROVIDER = "ollama"
LLAMA32_3B_MODEL = "llama3.2:3b"


@dataclass(frozen=True)
class ModelMetadata:
    provider: str
    model_id: str
    published_context_limit_tokens: int | None
    effective_context_limit_tokens: int | None
    maximum_output_tokens: int | None
    tokenizer_id: str | None
    metadata_source: str | None
    metadata_notes: tuple[str, ...] = ()


_MODELS = {
    (OLLAMA_PROVIDER, LLAMA32_3B_MODEL): ModelMetadata(
        provider=OLLAMA_PROVIDER,
        model_id=LLAMA32_3B_MODEL,
        # Ollama's published llama3.2:3b model metadata reports
        # llama.context_length=131072. This is not the runtime num_ctx value.
        published_context_limit_tokens=131072,
        effective_context_limit_tokens=None,
        maximum_output_tokens=None,
        # The published model metadata identifies llama-bpe, but a token-count
        # implementation for the installed local artifact is not yet verified.
        tokenizer_id=None,
        metadata_source="https://ollama.com/library/llama3.2",
        metadata_notes=(
            "Published model context is verified; effective Ollama runtime context is unknown.",
            "Installed model digest is not pinned by the configured tag.",
            "No verified tokenizer implementation is registered.",
            "No maximum output-token limit is configured or verified.",
        ),
    )
}

MODEL_REGISTRY = MappingProxyType(_MODELS)


class UnsupportedModelConfiguration(ValueError):
    """Raised when an exact provider/model pair is absent from the registry."""


def resolve_model(provider: str, model_id: str) -> ModelMetadata:
    """Resolve only an exact registered provider and model identifier."""
    try:
        return MODEL_REGISTRY[(provider, model_id)]
    except KeyError:
        raise UnsupportedModelConfiguration(
            "The configured provider/model pair is not registered."
        ) from None


__all__ = [
    "LLAMA32_3B_MODEL",
    "MODEL_REGISTRY",
    "ModelMetadata",
    "OLLAMA_PROVIDER",
    "UnsupportedModelConfiguration",
    "resolve_model",
]
