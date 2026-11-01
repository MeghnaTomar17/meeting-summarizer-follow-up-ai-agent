"""Shared security primitives for authenticated internal service requests."""

from shared.security.execution_context import TrustedExecutionContext
from shared.security.internal_principal import (
    create_internal_principal,
    verify_internal_principal,
)
from shared.security.service_principal import (
    create_service_principal,
    verify_service_principal,
)

__all__ = [
    "TrustedExecutionContext",
    "create_internal_principal",
    "verify_internal_principal",
    "create_service_principal",
    "verify_service_principal",
]
