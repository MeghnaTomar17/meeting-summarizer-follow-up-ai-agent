"""Shared security primitives for authenticated internal service requests."""

from shared.security.execution_context import TrustedExecutionContext
from shared.security.internal_principal import (
    create_internal_principal,
    verify_internal_principal,
)

__all__ = [
    "TrustedExecutionContext",
    "create_internal_principal",
    "verify_internal_principal",
]
