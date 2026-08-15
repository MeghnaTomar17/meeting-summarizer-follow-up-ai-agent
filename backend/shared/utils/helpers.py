"""
Purpose: Miscellaneous shared utilities.
Future responsibilities: ID generation, datetime helpers, pagination.
Service ownership: Shared module.
"""

from __future__ import annotations

from datetime import datetime, timezone

from shared.schemas.pagination import paginate_items as paginate

__all__ = ["paginate", "utc_now"]


def utc_now() -> datetime:
    """Return timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)
