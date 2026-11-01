"""Meeting Service-owned one-shot outbox command tests."""

from __future__ import annotations

import importlib
import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

BACKEND = Path(__file__).resolve().parents[1]
MEETING_ROOT = BACKEND / "meeting-service"
WORKER_ROOT = BACKEND / "worker-service"
NOW = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)


def _load_service(service_root: Path) -> None:
    for name in list(sys.modules):
        if name == "app" or name.startswith("app.") or name == "worker_queue" or name.startswith("worker_queue."):
            del sys.modules[name]
    for root in (str(MEETING_ROOT), str(WORKER_ROOT), str(BACKEND)):
        while root in sys.path:
            sys.path.remove(root)
    sys.path[:0] = [str(service_root), str(BACKEND)]


def _drive(coroutine):
    try:
        return coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("Mock-only command unexpectedly suspended on external I/O.")


class MeetingOutboxDispatchOnceTests(unittest.TestCase):
    def setUp(self) -> None:
        _load_service(MEETING_ROOT)
        self.module = importlib.import_module("app.outbox_dispatch_once")
        self.runtime_module = importlib.import_module("app.services.job_outbox_runtime")
        self.result_type = self.runtime_module.OneShotOutboxResult
        self.status_type = self.runtime_module.OneShotOutboxStatus
        self.settings = SimpleNamespace(
            processing_job_lease_seconds=960,
            outbox_publication_max_attempts=3,
            outbox_publication_max_ambiguity_recovery_claims=1,
            outbox_publication_retry_base_seconds=2.0,
            outbox_publication_retry_max_seconds=60.0,
        )
        self.event_id = UUID("60000000-0000-0000-0000-000000000006")

    def _configured_command(self, result=None, *, error=None):
        startup = AsyncMock()
        shutdown = AsyncMock()
        runtime = SimpleNamespace(run_once=AsyncMock(return_value=result))
        if error is not None:
            runtime.run_once.side_effect = error
        with patch.object(self.module, "get_settings", return_value=self.settings), patch.object(
            self.module, "startup_database", startup
        ), patch.object(self.module, "shutdown_database", shutdown), patch.object(
            self.module, "create_one_shot_outbox_runtime", return_value=runtime
        ) as runtime_factory, patch.object(self.module, "_utc_now", return_value=NOW):
            value = _drive(self.module.run_outbox_dispatch_once())
        return value, startup, shutdown, runtime, runtime_factory

    def test_invokes_existing_runtime_once_with_configured_lease_and_request_id(self) -> None:
        expected = self.result_type(status=self.status_type.PUBLISHED, event_id=self.event_id)
        result, startup, shutdown, runtime, runtime_factory = self._configured_command(expected)

        self.assertEqual(result, expected)
        startup.assert_awaited_once_with(self.settings)
        shutdown.assert_awaited_once()
        runtime.run_once.assert_awaited_once()
        kwargs = runtime.run_once.await_args.kwargs
        self.assertEqual(kwargs["locked_until"], NOW + timedelta(seconds=960))
        self.assertEqual(runtime_factory.call_count, 1)
        self.assertIs(runtime_factory.call_args.kwargs["settings"], self.settings)
        self.assertTrue(UUID(runtime_factory.call_args.kwargs["request_id"]))

    def test_no_work_is_a_successful_one_shot_outcome(self) -> None:
        expected = self.result_type(status=self.status_type.NO_WORK)
        result, _startup, shutdown, runtime, _runtime_factory = self._configured_command(expected)

        self.assertEqual(result.status, self.status_type.NO_WORK)
        runtime.run_once.assert_awaited_once()
        shutdown.assert_awaited_once()

    def test_exhausted_event_is_a_successful_operator_action_outcome(self) -> None:
        expected = self.result_type(
            status=self.status_type.EXHAUSTED, event_id=self.event_id
        )
        result, _startup, shutdown, runtime, _runtime_factory = self._configured_command(expected)

        self.assertEqual(result, expected)
        runtime.run_once.assert_awaited_once()
        shutdown.assert_awaited_once()

    def test_ambiguous_exhausted_event_is_reported_for_operator_action(self) -> None:
        expected = self.result_type(
            status=self.status_type.AMBIGUOUS_EXHAUSTED, event_id=self.event_id
        )
        stdout = io.StringIO()
        def return_result(coroutine):
            coroutine.close()
            return expected

        with patch.object(self.module.asyncio, "run", side_effect=return_result), redirect_stdout(stdout):
            exit_code = self.module.main()
        self.assertEqual(exit_code, 0)
        self.assertIn("ambiguous publication recovery exhausted", stdout.getvalue())

    def test_meeting_outbox_retry_settings_are_dedicated_and_bounded(self) -> None:
        from pydantic import ValidationError
        from app.config.settings import MeetingSettings

        defaults = MeetingSettings(_env_file=None)
        self.assertEqual(defaults.outbox_publication_max_attempts, 3)
        self.assertEqual(defaults.outbox_publication_max_ambiguity_recovery_claims, 1)
        self.assertEqual(defaults.outbox_publication_retry_base_seconds, 2)
        self.assertEqual(defaults.outbox_publication_retry_max_seconds, 60)
        with self.assertRaises(ValidationError):
            MeetingSettings(_env_file=None, outbox_publication_max_attempts=0)
        with self.assertRaises(ValidationError):
            MeetingSettings(_env_file=None, outbox_publication_max_ambiguity_recovery_claims=2)

        maximum_policy = MeetingSettings(
            _env_file=None,
            outbox_publication_max_attempts=3,
            outbox_publication_max_ambiguity_recovery_claims=1,
            outbox_publication_retry_base_seconds=2,
            outbox_publication_retry_max_seconds=60,
        )
        self.assertEqual(maximum_policy.outbox_publication_max_attempts, 3)
        self.assertEqual(maximum_policy.outbox_publication_retry_base_seconds, 2)
        self.assertEqual(maximum_policy.outbox_publication_retry_max_seconds, 60)

        lower_bound_policy = MeetingSettings(
            _env_file=None,
            outbox_publication_max_attempts=1,
            outbox_publication_max_ambiguity_recovery_claims=0,
            outbox_publication_retry_base_seconds=0.1,
            outbox_publication_retry_max_seconds=0.1,
        )
        self.assertEqual(lower_bound_policy.outbox_publication_max_attempts, 1)
        self.assertEqual(lower_bound_policy.outbox_publication_max_ambiguity_recovery_claims, 0)

        invalid_policy_values = (
            {"outbox_publication_max_attempts": 4},
            {"outbox_publication_retry_base_seconds": 2.01},
            {"outbox_publication_retry_max_seconds": 60.01},
            {
                "outbox_publication_retry_base_seconds": 2,
                "outbox_publication_retry_max_seconds": 1,
            },
        )
        for values in invalid_policy_values:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                MeetingSettings(_env_file=None, **values)

    def test_runtime_failure_propagates_and_database_still_shuts_down(self) -> None:
        with patch.object(self.module, "get_settings", return_value=self.settings), patch.object(
            self.module, "startup_database", AsyncMock()
        ) as startup, patch.object(self.module, "shutdown_database", AsyncMock()) as shutdown, patch.object(
            self.module, "create_one_shot_outbox_runtime",
            return_value=SimpleNamespace(run_once=AsyncMock(side_effect=RuntimeError("publish failed"))),
        ), patch.object(self.module, "_utc_now", return_value=NOW):
            with self.assertRaisesRegex(RuntimeError, "publish failed"):
                _drive(self.module.run_outbox_dispatch_once())

        startup.assert_awaited_once()
        shutdown.assert_awaited_once()

    def test_shutdown_failure_does_not_mask_primary_runtime_failure(self) -> None:
        primary = RuntimeError("runtime failure")
        with patch.object(self.module, "get_settings", return_value=self.settings), patch.object(
            self.module, "startup_database", AsyncMock()
        ), patch.object(
            self.module, "shutdown_database", AsyncMock(side_effect=OSError("cleanup failure"))
        ) as shutdown, patch.object(
            self.module, "create_one_shot_outbox_runtime",
            return_value=SimpleNamespace(run_once=AsyncMock(side_effect=primary)),
        ), patch.object(self.module, "_utc_now", return_value=NOW):
            with self.assertRaises(RuntimeError) as raised:
                _drive(self.module.run_outbox_dispatch_once())

        self.assertIs(raised.exception, primary)
        self.assertTrue(any("OSError" in note for note in getattr(primary, "__notes__", [])))
        shutdown.assert_awaited_once()

    def test_cli_reports_no_work_and_failures_without_exception_details(self) -> None:
        no_work = self.result_type(status=self.status_type.NO_WORK)
        stdout = io.StringIO()
        def return_no_work(coroutine):
            coroutine.close()
            return no_work

        with patch.object(self.module.asyncio, "run", side_effect=return_no_work) as run, redirect_stdout(stdout):
            exit_code = self.module.main()
        self.assertEqual(exit_code, 0)
        self.assertIn("no eligible", stdout.getvalue().lower())
        run.assert_called_once()

        stderr = io.StringIO()

        def fail_without_details(coroutine):
            coroutine.close()
            raise RuntimeError("database_password=do-not-print")

        with patch.object(
            self.module.asyncio,
            "run",
            side_effect=fail_without_details,
        ), redirect_stderr(stderr):
            exit_code = self.module.main()
        self.assertEqual(exit_code, 1)
        self.assertNotIn("do-not-print", stderr.getvalue())

    def test_invalid_configuration_fails_before_database_startup(self) -> None:
        startup = AsyncMock()
        with patch.object(
            self.module, "get_settings", side_effect=RuntimeError("configuration unavailable")
        ), patch.object(self.module, "startup_database", startup), patch.object(
            self.module, "shutdown_database", AsyncMock()
        ):
            with self.assertRaisesRegex(RuntimeError, "configuration unavailable"):
                _drive(self.module.run_outbox_dispatch_once())

        startup.assert_not_awaited()

    def test_startup_failure_still_attempts_database_cleanup(self) -> None:
        startup = AsyncMock(side_effect=RuntimeError("database startup failed"))
        shutdown = AsyncMock()
        with patch.object(self.module, "get_settings", return_value=self.settings), patch.object(
            self.module, "startup_database", startup
        ), patch.object(self.module, "shutdown_database", shutdown):
            with self.assertRaisesRegex(RuntimeError, "database startup failed"):
                _drive(self.module.run_outbox_dispatch_once())

        startup.assert_awaited_once_with(self.settings)
        shutdown.assert_awaited_once()

    def test_worker_registry_does_not_discover_meeting_outbox_runtime(self) -> None:
        _load_service(WORKER_ROOT)
        worker_settings = importlib.import_module("app.config.settings").WorkerSettings
        worker_celery = importlib.import_module("worker_queue.celery_app").celery_app

        self.assertNotIn("outbox_publication_auth_private_key", worker_settings.model_fields)
        self.assertNotIn("background_job_signing_private_key", worker_settings.model_fields)
        self.assertEqual(tuple(worker_celery.conf.include), ("jobs.ai_processing_task",))

    def test_meeting_api_lifespan_does_not_dispatch_outbox_on_startup(self) -> None:
        _load_service(MEETING_ROOT)
        main_module = importlib.import_module("app.main")
        with patch.object(main_module, "get_settings", return_value=self.settings), patch.object(
            main_module, "startup_database", AsyncMock()
        ), patch.object(main_module, "shutdown_database", AsyncMock()):
            manager = main_module.lifespan(main_module.app)
            self.assertIsNone(_drive(manager.__aenter__()))
            _drive(manager.__aexit__(None, None, None))

        self.assertNotIn("app.outbox_dispatch_once", sys.modules)


if __name__ == "__main__":
    unittest.main()
