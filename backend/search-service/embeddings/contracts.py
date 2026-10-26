"""Provider-neutral embedding request, response, and model identity contracts."""

from __future__ import annotations

import math
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EmbeddingModelIdentity(BaseModel):
    """Configured identity and output dimensionality of one embedding model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    dimensions: int = Field(ge=1)

    @field_validator("provider", "model")
    @classmethod
    def require_nonblank_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Embedding provider and model identity must not be blank")
        return normalized


class EmbeddingRequest(BaseModel):
    """Text batch plus the requested model identity; contains no provider SDK state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_identity: EmbeddingModelIdentity
    texts: list[str] = Field(min_length=1)

    @field_validator("texts")
    @classmethod
    def require_texts(cls, texts: list[str]) -> list[str]:
        if any(not text.strip() for text in texts):
            raise ValueError("Embedding input texts must not be blank")
        return texts


class EmbeddingResponse(BaseModel):
    """Provider-neutral vectors bound to the exact model identity and dimensions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_identity: EmbeddingModelIdentity
    vectors: list[list[float]] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_vector_values(self) -> EmbeddingResponse:
        for vector in self.vectors:
            if len(vector) != self.model_identity.dimensions:
                raise ValueError("Embedding vector dimensions do not match model identity")
            if any(not math.isfinite(value) for value in vector):
                raise ValueError("Embedding vectors must contain only finite values")
        return self


class EmbeddingProvider(Protocol):
    """Provider port implemented by Search Service infrastructure adapters."""

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse: ...

    async def aclose(self) -> None: ...


__all__ = [
    "EmbeddingModelIdentity",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "EmbeddingProvider",
]
