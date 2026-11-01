"""Shared, sanitized failure taxonomy for outbox publication attempts."""

from __future__ import annotations

from enum import StrEnum

MAX_OUTBOX_PUBLICATION_ATTEMPTS = 3
MAX_OUTBOX_AMBIGUITY_RECOVERY_CLAIMS = 1
MAX_OUTBOX_RETRY_BASE_SECONDS = 2.0
MAX_OUTBOX_RETRY_CAP_SECONDS = 60.0


class OutboxFailureCategory(StrEnum):
    CONFIGURATION_INVALID = "configuration_invalid"
    EVENT_INVALID = "event_invalid"
    AUTHENTICATION_REJECTED = "authentication_rejected"
    REQUEST_REJECTED = "request_rejected"
    TRANSPORT_UNAVAILABLE = "transport_unavailable"
    BROKER_UNAVAILABLE = "broker_unavailable"
    PROTOCOL_ERROR = "protocol_error"
    PUBLICATION_OUTCOME_UNKNOWN = "publication_outcome_unknown"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"
    AMBIGUOUS_RECOVERY_EXHAUSTED = "ambiguous_recovery_exhausted"

    @property
    def retryable(self) -> bool:
        return self in {
            OutboxFailureCategory.TRANSPORT_UNAVAILABLE,
            OutboxFailureCategory.BROKER_UNAVAILABLE,
        }

    @property
    def safe_message(self) -> str:
        return _SAFE_MESSAGES[self]


_SAFE_MESSAGES = {
    OutboxFailureCategory.CONFIGURATION_INVALID: "Publication configuration requires operator action.",
    OutboxFailureCategory.EVENT_INVALID: "The stored publication event is invalid.",
    OutboxFailureCategory.AUTHENTICATION_REJECTED: "Publication authentication was rejected.",
    OutboxFailureCategory.REQUEST_REJECTED: "The publication request was rejected.",
    OutboxFailureCategory.TRANSPORT_UNAVAILABLE: "The publication service could not be reached.",
    OutboxFailureCategory.BROKER_UNAVAILABLE: "The publication broker is temporarily unavailable.",
    OutboxFailureCategory.PROTOCOL_ERROR: "The publication response was invalid.",
    OutboxFailureCategory.PUBLICATION_OUTCOME_UNKNOWN: "Publication outcome is unknown; a bounded recovery claim is pending.",
    OutboxFailureCategory.ATTEMPTS_EXHAUSTED: "Publication attempts were exhausted.",
    OutboxFailureCategory.AMBIGUOUS_RECOVERY_EXHAUSTED: "Ambiguous publication recovery was exhausted; operator action is required.",
}


class OutboxPublicationError(RuntimeError):
    """A safe category-only publication failure; never carries provider text."""

    def __init__(self, category: OutboxFailureCategory) -> None:
        self.category = category
        super().__init__(category.safe_message)


def outbox_retry_delay(
    attempt_count: int, *, base_seconds: float, maximum_seconds: float
) -> float:
    """Bounded exponential delay for a one-based failed publication attempt."""
    if type(attempt_count) is not int or attempt_count < 1:
        raise ValueError("Outbox attempt count must be a positive integer.")
    if (
        base_seconds <= 0
        or base_seconds > MAX_OUTBOX_RETRY_BASE_SECONDS
        or maximum_seconds < base_seconds
        or maximum_seconds > MAX_OUTBOX_RETRY_CAP_SECONDS
    ):
        raise ValueError("Outbox retry delay settings are invalid.")
    return min(maximum_seconds, base_seconds * (2 ** (attempt_count - 1)))


__all__ = [
    "MAX_OUTBOX_PUBLICATION_ATTEMPTS",
    "MAX_OUTBOX_AMBIGUITY_RECOVERY_CLAIMS",
    "MAX_OUTBOX_RETRY_BASE_SECONDS",
    "MAX_OUTBOX_RETRY_CAP_SECONDS",
    "OutboxFailureCategory",
    "OutboxPublicationError",
    "outbox_retry_delay",
]
