"""Tests for the Phase 6 Block 1 AI Service boundary."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
AI_SERVICE_ROOT = BACKEND_ROOT / "ai-service"
SERVICE_NAMES = (
    "gateway-service",
    "meeting-service",
    "ai-service",
    "search-service",
    "worker-service",
)

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _load_ai_module(module_name: str):
    """Import an AI module without reusing another service's generic `app` package."""
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]
    for service_name in SERVICE_NAMES:
        service_root = str(BACKEND_ROOT / service_name)
        while service_root in sys.path:
            sys.path.remove(service_root)
    sys.path.insert(0, str(AI_SERVICE_ROOT))
    return importlib.import_module(module_name)


class AIServiceConfigurationTestCase(unittest.TestCase):
    def test_configuration_loads_without_provider_credentials(self) -> None:
        module = _load_ai_module("app.config.settings")

        settings = module.AISettings(
            app_env="testing",
            openai_api_key=None,
            gemini_api_key=None,
        )

        self.assertEqual(settings.service_name, "ai-service")
        self.assertEqual(settings.app_env.value, "testing")
        self.assertIsNone(settings.openai_api_key)
        self.assertIsNone(settings.gemini_api_key)
        self.assertIsNone(settings.openai_model)
        self.assertIsNone(settings.gemini_model)

    def test_invalid_shared_configuration_is_rejected(self) -> None:
        module = _load_ai_module("app.config.settings")

        with self.assertRaises(ValidationError):
            module.AISettings(log_level="TRACE")


class AIProcessingContractTestCase(unittest.TestCase):
    def test_valid_request_and_future_result_contract_validate(self) -> None:
        module = _load_ai_module("app.contracts")
        request = module.ProcessingRequest.model_validate(
            {
                "meeting_id": "d146f98d-d557-4b89-a746-3e48e73d46b1",
                "transcript_id": "084c3a14-1a7f-41c9-a7c8-1e195aa5313a",
                "requested_operations": ["summary", "tasks"],
                "context": {"locale": "en"},
            }
        )
        result = module.ProcessingResult(
            meeting_id=request.meeting_id,
            transcript_id=request.transcript_id,
            requested_operations=request.requested_operations,
            status=module.ProcessingStatus.NOT_IMPLEMENTED,
        )

        self.assertEqual(
            request.requested_operations[0], module.ProcessingOperation.SUMMARY
        )
        self.assertEqual(result.status.value, "not_implemented")
        self.assertEqual(result.sections, {})
        self.assertEqual(result.model_dump(mode="json")["status"], "not_implemented")
        self.assertEqual(result.model_dump(mode="json")["sections"], {})

    def test_invalid_or_client_owned_request_fields_are_rejected(self) -> None:
        module = _load_ai_module("app.contracts")
        base = {
            "meeting_id": "d146f98d-d557-4b89-a746-3e48e73d46b1",
            "transcript_id": "084c3a14-1a7f-41c9-a7c8-1e195aa5313a",
        }

        with self.assertRaises(ValidationError):
            module.ProcessingRequest.model_validate(
                {**base, "requested_operations": []}
            )
        with self.assertRaises(ValidationError):
            module.ProcessingRequest.model_validate(
                {**base, "requested_operations": ["unknown"]}
            )
        with self.assertRaises(ValidationError):
            module.ProcessingRequest.model_validate(
                {**base, "requested_operations": ["summary"], "created_by": "user-id"}
            )


class AIServiceOrchestrationTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_orchestrator_is_independent_and_never_returns_fake_success(self) -> None:
        contracts = _load_ai_module("app.contracts")
        orchestrator_module = _load_ai_module("agents.orchestrator")
        request = contracts.ProcessingRequest(
            meeting_id="d146f98d-d557-4b89-a746-3e48e73d46b1",
            transcript_id="084c3a14-1a7f-41c9-a7c8-1e195aa5313a",
            requested_operations=["summary", "tasks"],
        )

        orchestrator = orchestrator_module.AIProcessingOrchestrator()
        result = await orchestrator.process(request)

        self.assertEqual(result.status, contracts.ProcessingStatus.NOT_IMPLEMENTED)
        self.assertEqual(result.sections, {})
        self.assertEqual(result.requested_operations, request.requested_operations)

    def test_imports_work_without_provider_clients_or_sqlalchemy(self) -> None:
        blocked_imports = """
import builtins
real_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name == 'openai' or name.startswith('google') or name == 'sqlalchemy':
        raise AssertionError('provider and ORM imports are forbidden in the foundation')
    return real_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
import asyncio
from app.contracts import ProcessingRequest
from agents.orchestrator import AIProcessingOrchestrator
request = ProcessingRequest(
    meeting_id='d146f98d-d557-4b89-a746-3e48e73d46b1',
    transcript_id='084c3a14-1a7f-41c9-a7c8-1e195aa5313a',
    requested_operations=['summary'],
)
result = asyncio.run(AIProcessingOrchestrator().process(request))
assert result.status.value == 'not_implemented' and result.sections == {}
"""
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            (str(AI_SERVICE_ROOT), str(BACKEND_ROOT))
        )
        result = subprocess.run(
            [sys.executable, "-c", blocked_imports],
            cwd=BACKEND_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)


class AIServiceApplicationTestCase(unittest.TestCase):
    def test_health_and_readiness_are_independent_of_database_and_provider(self) -> None:
        main_module = _load_ai_module("app.main")

        with TestClient(main_module.app) as client:
            for path in ("/health", "/health/live", "/health/ready"):
                with self.subTest(path=path):
                    response = client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["service"], "ai-service")
