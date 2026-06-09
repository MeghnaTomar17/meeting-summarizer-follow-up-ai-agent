"""
Purpose: Shared validation helpers.
Future responsibilities: File type/size checks, email domains, ID formats.
Service ownership: Shared module.
"""

from __future__ import annotations

import uuid
from typing import Any


def is_valid_uuid(value: str) -> bool:
    """Validate UUID string format (PostgreSQL primary keys)."""
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


def validate_upload_metadata(filename: str, content_type: str, size_bytes: int) -> None:
    """Validate upload constraints — TODO: enforce allowlists and max size."""
    _ = (filename, content_type, size_bytes)
    raise NotImplementedError("Upload validation not implemented")


def sanitize_text(text: str, max_length: int = 100_000) -> str:
    """Basic text sanitization placeholder."""
    return text[:max_length]


def ensure_not_empty(value: Any, field_name: str) -> Any:
    """Raise if value is None or empty string."""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{field_name} must not be empty")
    return value
