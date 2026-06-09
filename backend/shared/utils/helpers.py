"""
Purpose: Miscellaneous shared utilities.
Future responsibilities: ID generation, datetime helpers, pagination.
Service ownership: Shared module.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TypeVar

T = TypeVar("T")


def utc_now() -> datetime:
    """Return timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def paginate(items: list[T], page: int, page_size: int) -> tuple[list[T], int]:
    """Slice items for offset pagination — TODO: cursor-based pagination."""
    if page < 1:
        page = 1
    start = (page - 1) * page_size
    end = start + page_size
    return items[start:end], len(items)
