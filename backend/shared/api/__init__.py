"""Shared API contract utilities and constants."""

from shared.api.constants import (
    API_V1_PREFIX,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
)
from shared.api.openapi import COMMON_ERROR_RESPONSES

__all__ = [
    "API_V1_PREFIX",
    "COMMON_ERROR_RESPONSES",
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
]
