"""Mock-only coverage for the non-generation Ollama render diagnostic."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = BACKEND_ROOT / "scripts" / "ollama_prompt_render_check.py"
SPEC = importlib.util.spec_from_file_location("ollama_prompt_render_check", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


class OllamaPromptRenderDiagnosticTestCase(unittest.TestCase):
    def test_payloads_use_actual_agent_builders_and_debug_only_flag(self) -> None:
        requests = probe.build_probe_requests()

        self.assertEqual(
            [name for name, _ in requests],
            ["summary", "tasks", "decisions", "followups", "insights", "cross_meeting_answer"],
        )
        for _, payload in requests:
            self.assertEqual(payload["model"], "llama3.2:3b")
            self.assertEqual([item["role"] for item in payload["messages"]], ["system", "user"])
            self.assertTrue(payload["format"]["properties"])
            self.assertEqual(payload["options"], {})
            self.assertIs(payload["stream"], False)
            self.assertIs(payload["_debug_render_only"], True)

    def test_render_response_accepts_ollama_empty_debug_message(self) -> None:
        client = Mock()
        client.post.return_value = SimpleNamespace(
            raise_for_status=Mock(),
            json=Mock(
                return_value={
                    "model": "llama3.2:3b",
                    "done": False,
                    "message": {"role": "assistant", "content": "", "tool_calls": []},
                    "_debug_info": {"rendered_template": "rendered prompt"},
                }
            ),
        )
        rendered = probe.get_rendered_template(client, {"_debug_render_only": True})
        self.assertEqual(rendered, "rendered prompt")
        self.assertTrue(client.post.call_args.kwargs["json"]["_debug_render_only"])

    def test_render_response_rejects_generated_message_content_or_tools(self) -> None:
        client = Mock()
        client.post.return_value.raise_for_status = Mock()
        for message in (
            {"role": "assistant", "content": "generated text"},
            {"role": "assistant", "content": "", "tool_calls": [{"name": "tool"}]},
            {"role": "assistant", "content": "", "thinking": "reasoning"},
        ):
            with self.subTest(message=message):
                client.post.return_value.json.return_value = {
                    "model": "llama3.2:3b",
                    "done": False,
                    "message": message,
                    "_debug_info": {"rendered_template": "rendered prompt"},
                }
                with self.assertRaises(RuntimeError):
                    probe.get_rendered_template(client, {"_debug_render_only": True})

    def test_render_response_rejects_malformed_or_incomplete_debug_shapes(self) -> None:
        client = Mock()
        client.post.return_value.raise_for_status = Mock()
        for body in (
            [],
            {"model": "llama3.2:3b", "done": False, "_debug_info": {"rendered_template": "x"}},
            {"model": "llama3.2:3b", "done": False, "message": None, "_debug_info": {"rendered_template": "x"}},
            {"model": "llama3.2:3b", "done": False, "message": {}, "_debug_info": {"rendered_template": "x"}},
            {"model": "llama3.2:3b", "done": False, "message": "empty"},
            {"model": "llama3.2:3b", "done": False, "message": {"role": "assistant"}, "_debug_info": {"rendered_template": "x"}},
            {"model": "llama3.2:3b", "done": True, "_debug_info": {"rendered_template": "x"}},
            {"model": "another-model", "done": False, "_debug_info": {"rendered_template": "x"}},
            {"model": "llama3.2:3b", "done": False, "response": "generated", "_debug_info": {"rendered_template": "x"}},
            {"model": "llama3.2:3b", "done": False},
            {"model": "llama3.2:3b", "done": False, "_debug_info": []},
            {"model": "llama3.2:3b", "done": False, "_debug_info": {"rendered_template": ""}},
            {"model": "llama3.2:3b", "done": False, "_debug_info": {"rendered_template": None}},
        ):
            with self.subTest(body=body):
                client.post.return_value.json.return_value = body
                with self.assertRaises(RuntimeError):
                    probe.get_rendered_template(client, {"_debug_render_only": True})


if __name__ == "__main__":
    unittest.main()
