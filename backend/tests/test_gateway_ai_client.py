"""Signed AI Service client forwarding tests."""

from __future__ import annotations

import importlib
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization

BACKEND = Path(__file__).resolve().parents[1]
GATEWAY_ROOT = BACKEND / "gateway-service"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _load():
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    while str(GATEWAY_ROOT) in sys.path:
        sys.path.remove(str(GATEWAY_ROOT))
    sys.path.insert(0, str(GATEWAY_ROOT))
    return importlib.import_module("app.services.ai_client")


class GatewayAIClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_ai_call_uses_ai_audience_authenticated_owner_and_request_id(self):
        module = _load()
        from app.config.settings import GatewaySettings
        from shared.schemas.cross_meeting import (
            CrossMeetingAnswerGenerationRequest, CrossMeetingEvidenceBundle,
            CrossMeetingStructuredData,
        )
        from shared.schemas.pagination import build_paginated_response
        from shared.schemas.semantic_search import SemanticSearchResponse

        page = build_paginated_response([], page=1, page_size=20, total=0)
        evidence = CrossMeetingEvidenceBundle(
            structured=CrossMeetingStructuredData(meetings=page, tasks=page, decisions=page, insights=page),
            semantic=SemanticSearchResponse(results=[]),
        )
        payload = CrossMeetingAnswerGenerationRequest(question="What happened?", evidence=evidence)
        settings = GatewaySettings(_env_file=None)
        owner_id = uuid.uuid4()
        captured = {}

        class Response:
            status_code = 200
            @staticmethod
            def json():
                return {"answer": "Insufficient evidence.", "insufficient_evidence": True, "citations": []}

        class Client:
            async def __aenter__(self): return self
            async def __aexit__(self, *_args): return None
            async def post(self, path, *, json, headers):
                captured.update(path=path, json=json, headers=headers)
                return Response()

        with patch.object(module.httpx, "AsyncClient", return_value=Client()):
            result = await module.AIServiceClient(settings).answer(
                payload, user_id=owner_id, request_id="ai-request-77"
            )

        private_key = serialization.load_pem_private_key(
            settings.internal_principal_private_key.get_secret_value().encode(), password=None
        )
        public_pem = private_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode()
        from shared.security.internal_principal import verify_internal_principal
        token = captured["headers"]["Authorization"].removeprefix("Bearer ")
        self.assertEqual(verify_internal_principal(
            token, public_key=public_pem, algorithm="RS256",
            issuer="gateway-service", audience="ai-service",
        ), owner_id)
        self.assertEqual(captured["headers"]["X-Request-ID"], "ai-request-77")
        self.assertEqual(captured["path"], "/internal/intelligence/answers")
        self.assertEqual(captured["json"]["question"], payload.question)
        self.assertEqual(result.insufficient_evidence, True)


if __name__ == "__main__":
    unittest.main()
