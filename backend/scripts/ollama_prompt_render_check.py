"""Render real AI request shapes through Ollama without invoking generation.

This operator-run diagnostic is intentionally pinned to the locally verified
Ollama/model identity. Ollama 0.40.12's `_debug_render_only` path returns the
rendered template before calling completion. The script prints only hashes and
character lengths, never prompt content.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx


BACKEND_ROOT = Path(__file__).resolve().parents[1]
AI_SERVICE_ROOT = BACKEND_ROOT / "ai-service"
for _service in ("gateway-service", "meeting-service", "ai-service", "search-service", "worker-service"):
    _path = str(BACKEND_ROOT / _service)
    while _path in sys.path:
        sys.path.remove(_path)
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(AI_SERVICE_ROOT))


OLLAMA_BASE_URL = "http://localhost:11434"
EXPECTED_VERSION = "0.40.12"
EXPECTED_MODEL = "llama3.2:3b"
EXPECTED_MODEL_ID_PREFIX = "a80c4f17acd5"


def build_probe_requests() -> list[tuple[str, dict[str, Any]]]:
    """Build test-only payloads with the application's actual agent builders."""
    from agents.cross_meeting_agent import CrossMeetingAnswerAgent, CrossMeetingAnswerOutput
    from agents.decision_agent import DecisionAgent
    from agents.followup_agent import FollowUpAgent
    from agents.insight_agent import InsightAgent
    from agents.summary_agent import SummaryAgent
    from agents.task_agent import TaskAgent
    from app.contracts import AgentInput, TranscriptContent
    from shared.schemas.cross_meeting import (
        CrossMeetingEvidenceBundle,
        CrossMeetingStructuredData,
    )
    from shared.schemas.pagination import build_paginated_response
    from shared.schemas.semantic_search import SemanticSearchResponse
    from shared.schemas.transcript import TranscriptSegment

    transcript = TranscriptContent(
        transcript_id=UUID("8a1d24d8-5c58-4b7d-a4fb-c9b22d7309a1"),
        language="en",
        segments=[
            TranscriptSegment(
                index=0,
                speaker="Speaker A",
                text="The team agreed to review the draft next week.",
                start_ms=0,
                end_ms=1500,
            )
        ],
    )
    agent_input = AgentInput(
        meeting_id=UUID("56bb7802-1b55-484e-a0bd-d4e0bc06aaca"),
        transcript=transcript,
    )
    requests: list[tuple[str, dict[str, Any]]] = []
    for name, agent_type in (
        ("summary", SummaryAgent),
        ("tasks", TaskAgent),
        ("decisions", DecisionAgent),
        ("followups", FollowUpAgent),
        ("insights", InsightAgent),
    ):
        agent = agent_type(model_provider=None)
        request = agent.build_model_request(agent_input)
        requests.append((name, _chat_payload(request, agent.output_model.model_json_schema())))

    empty_page = build_paginated_response([], page=1, page_size=1, total=0)
    evidence = CrossMeetingEvidenceBundle(
        structured=CrossMeetingStructuredData(
            meetings=empty_page,
            tasks=empty_page,
            decisions=empty_page,
            insights=empty_page,
        ),
        semantic=SemanticSearchResponse(results=[]),
    )
    cross_request = CrossMeetingAnswerAgent.build_question_request(
        "What did the team agree to do?",
        evidence,
        now="2026-10-31T00:00:00+00:00",
    )
    requests.append(
        (
            "cross_meeting_answer",
            _chat_payload(cross_request, CrossMeetingAnswerOutput.model_json_schema()),
        )
    )
    return requests


def _chat_payload(request: Any, response_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": EXPECTED_MODEL,
        "messages": [
            {"role": "system", "content": request.instructions},
            {"role": "user", "content": request.input_text},
        ],
        "format": response_schema,
        # No context/output values are supplied because those are not verified.
        "options": {},
        "stream": False,
        "_debug_render_only": True,
    }


def verify_local_identity(client: httpx.Client) -> None:
    version_response = client.get(f"{OLLAMA_BASE_URL}/api/version")
    version_response.raise_for_status()
    version = version_response.json().get("version")
    if version != EXPECTED_VERSION:
        raise RuntimeError(f"Expected Ollama {EXPECTED_VERSION}; found {version!r}.")

    tags_response = client.get(f"{OLLAMA_BASE_URL}/api/tags")
    tags_response.raise_for_status()
    models = tags_response.json().get("models", [])
    match = next(
        (item for item in models if item.get("name") == EXPECTED_MODEL), None
    )
    digest = match.get("digest", "") if match else ""
    if not digest.startswith(EXPECTED_MODEL_ID_PREFIX):
        raise RuntimeError("The expected local Ollama model ID was not found.")


def get_rendered_template(client: httpx.Client, payload: dict[str, Any]) -> str:
    response = client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError("Ollama returned an invalid debug response shape.")

    message = body.get("message")
    if (
        not isinstance(message, dict)
        or not isinstance(message.get("role"), str)
        or not isinstance(message.get("content"), str)
        or message["content"] != ""
        or message.get("thinking", "") not in (None, "")
        or message.get("tool_calls", []) not in (None, [])
    ):
        raise RuntimeError("Ollama returned an invalid or generated message in debug rendering.")

    # ChatResponse serializes its zero-value message struct as an object with
    # role/content fields, even when debug rendering produced no message.
    if (
        body.get("model") != EXPECTED_MODEL
        or body.get("done") is not False
    ):
        raise RuntimeError("Ollama did not return a debug-only render response.")
    if body.get("response", "") != "":
        raise RuntimeError("Ollama returned generated content during debug rendering.")
    debug_info = body.get("_debug_info")
    if not isinstance(debug_info, dict):
        raise RuntimeError("Ollama returned no debug information.")
    rendered = debug_info.get("rendered_template") if isinstance(debug_info, dict) else None
    if not isinstance(rendered, str) or not rendered:
        raise RuntimeError("Ollama returned no rendered template.")
    return rendered


def main() -> int:
    try:
        with httpx.Client(timeout=10.0) as client:
            verify_local_identity(client)
            for name, payload in build_probe_requests():
                rendered = get_rendered_template(client, payload)
                print(
                    f"{name}: sha256={hashlib.sha256(rendered.encode('utf-8')).hexdigest()} "
                    f"characters={len(rendered)}"
                )
    except (httpx.HTTPError, ValueError, RuntimeError) as error:
        print(f"Prompt render check failed: {error}", file=sys.stderr)
        return 1
    print("Rendered six request shapes; no generation was requested.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
