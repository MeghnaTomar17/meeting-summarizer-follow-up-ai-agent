"""
Purpose: Request-scoped logging context via contextvars.
Service ownership: Shared module.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, Iterator

_log_context: ContextVar[dict[str, Any] | None] = ContextVar("log_context", default=None)

CONTEXT_FIELD_NAMES = frozenset(
    {
        "request_id",
        "method",
        "path",
        "status_code",
        "duration_ms",
        "meeting_id",
        "user_id",
        "job_id",
        "task_name",
        "event",
    }
)


def get_log_context() -> dict[str, Any]:
    """Return a copy of the current logging context."""
    current = _log_context.get()
    return {} if current is None else dict(current)


def set_log_context(values: dict[str, Any]) -> Token[dict[str, Any]]:
    """Merge values into the current context and return a reset token."""
    current = _log_context.get()
    base = {} if current is None else dict(current)
    return _log_context.set({**base, **values})


def reset_log_context(token: Token[dict[str, Any]]) -> None:
    """Restore logging context from a token returned by set_log_context."""
    _log_context.reset(token)


@contextmanager
def bind_context(**kwargs: Any) -> Iterator[dict[str, Any]]:
    """Bind contextual fields for the duration of a scoped block."""
    token = set_log_context(kwargs)
    try:
        yield get_log_context()
    finally:
        reset_log_context(token)
