"""Shared security primitives for authenticated internal service requests."""

from shared.security.internal_principal import (
    create_internal_principal,
    verify_internal_principal,
)

__all__ = ["create_internal_principal", "verify_internal_principal"]
