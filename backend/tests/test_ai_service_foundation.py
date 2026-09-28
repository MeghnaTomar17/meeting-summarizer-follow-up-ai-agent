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
        if any(
            key == package or key.startswith(f"{package}.")
            for package in ("app", "agents", "llm", "pipelines")
        ):
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
        result_models = importlib.import_module("app.processing_results")
        request = module.ProcessingRequest.model_validate(
            {
                "meeting_id": "d146f98d-d557-4b89-a746-3e48e73d46b1",
                "transcript_id": "084c3a14-1a7f-41c9-a7c8-1e195aa5313a",
                "requested_operations": ["summary", "tasks"],
                "context": {"locale": "en"},
            }
        )
        result = result_models.ProcessingResult(
            meeting_id=request.meeting_id,
            transcript_id=request.transcript_id,
            requested_operations=request.requested_operations,
            status=module.ProcessingStatus.COMPLETED,
            results=[
                result_models.OperationResult(
                    operation=module.ProcessingOperation.SUMMARY,
                    status=result_models.OperationStatus.COMPLETED,
                    output=importlib.import_module("agents.summary_agent").SummaryAgentOutput(
                        content="A concise summary.", key_topics=[]
                    ),
                ),
                result_models.OperationResult(
                    operation=module.ProcessingOperation.TASKS,
                    status=result_models.OperationStatus.COMPLETED,
                    output=importlib.import_module("agents.task_agent").TaskAgentOutput(
                        tasks=[]
                    ),
                ),
            ],
        )

        self.assertEqual(
            request.requested_operations[0], module.ProcessingOperation.SUMMARY
        )
        self.assertEqual(result.status.value, "completed")
        self.assertEqual(len(result.results), 2)
        self.assertEqual(result.model_dump(mode="json")["status"], "completed")
        self.assertEqual(result.results[0].operation, module.ProcessingOperation.SUMMARY)

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
    async def test_orchestrator_reports_unconfigured_provider_without_fake_success(self) -> None:
        orchestrator_module = _load_ai_module("agents.orchestrator")
        contracts = importlib.import_module("app.contracts")
        results_module = importlib.import_module("app.processing_results")
        request = contracts.ProcessingRequest(
            meeting_id="d146f98d-d557-4b89-a746-3e48e73d46b1",
            transcript_id="084c3a14-1a7f-41c9-a7c8-1e195aa5313a",
            requested_operations=["summary", "tasks"],
        )
        agent_input = contracts.AgentInput(
            meeting_id=request.meeting_id,
            transcript={
                "transcript_id": request.transcript_id,
                "segments": [{"index": 0, "text": "Discussed project status."}],
            },
        )

        orchestrator = orchestrator_module.AIProcessingOrchestrator()
        result = await orchestrator.process(request, agent_input)

        self.assertEqual(result.status, contracts.ProcessingStatus.FAILED)
        self.assertEqual(
            [entry.error.code for entry in result.results],
            [
                results_module.ProcessingErrorCode.PROVIDER_NOT_CONFIGURED,
                results_module.ProcessingErrorCode.PROVIDER_NOT_CONFIGURED,
            ],
        )
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
from app.contracts import AgentInput, ProcessingRequest
from agents.orchestrator import AIProcessingOrchestrator
request = ProcessingRequest(
    meeting_id='d146f98d-d557-4b89-a746-3e48e73d46b1',
    transcript_id='084c3a14-1a7f-41c9-a7c8-1e195aa5313a',
    requested_operations=['summary'],
)
agent_input = AgentInput(
    meeting_id=request.meeting_id,
    transcript={
        'transcript_id': request.transcript_id,
        'segments': [{'index': 0, 'text': 'A meeting took place.'}],
    },
)
result = asyncio.run(AIProcessingOrchestrator().process(request, agent_input))
assert result.status.value == 'failed'
assert result.results[0].error.code.value == 'provider_not_configured'
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
