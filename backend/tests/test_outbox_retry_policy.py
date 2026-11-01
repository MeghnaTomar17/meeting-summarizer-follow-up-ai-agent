"""Pure outbox retry policy contracts; no database or service dependencies."""

from __future__ import annotations

import unittest

from shared.jobs.outbox_policy import (
    OutboxFailureCategory,
    OutboxPublicationError,
    outbox_retry_delay,
)


class OutboxRetryPolicyTests(unittest.TestCase):
    def test_only_transport_and_broker_failures_are_retryable(self) -> None:
        self.assertTrue(OutboxFailureCategory.TRANSPORT_UNAVAILABLE.retryable)
        self.assertTrue(OutboxFailureCategory.BROKER_UNAVAILABLE.retryable)
        for category in OutboxFailureCategory:
            if category not in {
                OutboxFailureCategory.TRANSPORT_UNAVAILABLE,
                OutboxFailureCategory.BROKER_UNAVAILABLE,
            }:
                with self.subTest(category=category):
                    self.assertFalse(category.retryable)

    def test_backoff_is_exponential_and_capped(self) -> None:
        delays = [
            outbox_retry_delay(attempt, base_seconds=2, maximum_seconds=60)
            for attempt in (1, 2, 3, 4, 5, 6)
        ]
        self.assertEqual(delays, [2, 4, 8, 16, 32, 60])

    def test_invalid_policy_inputs_fail_closed(self) -> None:
        for attempt in (0, -1, True, 1.5):
            with self.subTest(attempt=attempt), self.assertRaises(ValueError):
                outbox_retry_delay(attempt, base_seconds=2, maximum_seconds=60)
        with self.assertRaises(ValueError):
            outbox_retry_delay(1, base_seconds=0, maximum_seconds=60)
        with self.assertRaises(ValueError):
            outbox_retry_delay(1, base_seconds=3, maximum_seconds=2)
        with self.assertRaises(ValueError):
            outbox_retry_delay(1, base_seconds=2.01, maximum_seconds=60)
        with self.assertRaises(ValueError):
            outbox_retry_delay(1, base_seconds=2, maximum_seconds=60.01)

    def test_publication_errors_expose_only_allowlisted_safe_metadata(self) -> None:
        error = OutboxPublicationError(OutboxFailureCategory.BROKER_UNAVAILABLE)
        self.assertEqual(error.category, OutboxFailureCategory.BROKER_UNAVAILABLE)
        self.assertEqual(str(error), "The publication broker is temporarily unavailable.")
        self.assertNotIn("password", str(error))


if __name__ == "__main__":
    unittest.main()
