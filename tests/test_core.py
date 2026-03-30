from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent
SRC_ROOT = TESTS_ROOT.parent / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from codex_langfuse_exporter.core import build_payload
from codex_langfuse_exporter.core import parse_session


class ParseSessionTests(unittest.TestCase):
    def test_parse_session_extracts_turn_payload_and_skips_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            session_path = Path(tmpdir) / "session-019d3d85-2065-7dc0-b58c-5e31d9c80368.jsonl"
            lines = [
                {
                    "type": "session_meta",
                    "timestamp": "2026-03-30T01:00:00Z",
                    "payload": {"id": "sess-1", "cli_version": "0.1.0"},
                },
                {
                    "type": "event_msg",
                    "timestamp": "2026-03-30T01:00:01Z",
                    "payload": {"type": "task_started", "turn_id": "turn-1"},
                },
                {
                    "type": "turn_context",
                    "timestamp": "2026-03-30T01:00:02Z",
                    "payload": {"turn_id": "turn-1", "model": "gpt-5.4"},
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-03-30T01:00:03Z",
                    "payload": {
                        "turn_id": "turn-1",
                        "type": "message",
                        "role": "user",
                        "content": [{"text": "# AGENTS.md instructions for x\n<environment_context>"}],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-03-30T01:00:04Z",
                    "payload": {
                        "turn_id": "turn-1",
                        "type": "message",
                        "role": "user",
                        "content": [{"text": "Fix the failing test"}],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-03-30T01:00:05Z",
                    "payload": {
                        "turn_id": "turn-1",
                        "type": "message",
                        "role": "assistant",
                        "phase": "analysis",
                        "content": [{"text": "Looking at the repo now."}],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-03-30T01:00:06Z",
                    "payload": {
                        "turn_id": "turn-1",
                        "type": "message",
                        "role": "assistant",
                        "phase": "final",
                        "content": [{"text": "Patched the issue and added coverage."}],
                    },
                },
                {
                    "type": "event_msg",
                    "timestamp": "2026-03-30T01:00:07Z",
                    "payload": {
                        "turn_id": "turn-1",
                        "type": "token_count",
                        "info": {
                            "last_token_usage": {
                                "input_tokens": 120,
                                "cached_input_tokens": 20,
                                "output_tokens": 45,
                                "reasoning_output_tokens": 5,
                                "total_tokens": 165,
                            }
                        },
                    },
                },
            ]
            session_path.write_text(
                "".join(json.dumps(line) + "\n" for line in lines),
                encoding="utf-8",
            )

            session_id, cli_version, turns = parse_session(session_path)

        self.assertEqual(session_id, "sess-1")
        self.assertEqual(cli_version, "0.1.0")
        self.assertEqual(len(turns), 1)

        turn = turns[0]
        self.assertEqual(turn.user_messages, ["Fix the failing test"])
        self.assertEqual(turn.output_payload(), "Patched the issue and added coverage.")
        self.assertEqual(
            turn.usage.to_langfuse_usage(),
            {
                "input": 100,
                "input_cached_tokens": 20,
                "output": 40,
                "output_reasoning_tokens": 5,
                "total": 165,
            },
        )


class BuildPayloadTests(unittest.TestCase):
    def test_build_payload_creates_generation_span(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            session_path = Path(tmpdir) / "session-foo.jsonl"
            lines = [
                {
                    "type": "session_meta",
                    "timestamp": "2026-03-30T01:00:00Z",
                    "payload": {"id": "sess-2", "cli_version": "0.2.0"},
                },
                {
                    "type": "event_msg",
                    "timestamp": "2026-03-30T01:00:01Z",
                    "payload": {"type": "task_started", "turn_id": "turn-2"},
                },
                {
                    "type": "turn_context",
                    "timestamp": "2026-03-30T01:00:02Z",
                    "payload": {"turn_id": "turn-2", "model": "gpt-5.4"},
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-03-30T01:00:03Z",
                    "payload": {
                        "turn_id": "turn-2",
                        "type": "message",
                        "role": "user",
                        "content": [{"text": "Ship a release"}],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-03-30T01:00:04Z",
                    "payload": {
                        "turn_id": "turn-2",
                        "type": "message",
                        "role": "assistant",
                        "phase": "final",
                        "content": [{"text": "Release notes are ready."}],
                    },
                },
            ]
            session_path.write_text(
                "".join(json.dumps(line) + "\n" for line in lines),
                encoding="utf-8",
            )
            _, _, turns = parse_session(session_path)

        payload = build_payload(
            turns,
            public_key="pk-lf-test",
            cli_version="0.2.0",
            langfuse_environment="prod",
        )

        resource_spans = payload["resourceSpans"]
        self.assertEqual(len(resource_spans), 1)
        scope_span = resource_spans[0]["scopeSpans"][0]
        self.assertEqual(scope_span["scope"]["name"], "codex-langfuse-exporter")
        self.assertEqual(scope_span["scope"]["attributes"][0]["value"]["stringValue"], "pk-lf-test")

        span = scope_span["spans"][0]
        self.assertEqual(span["name"], "codex.turn.backfill")
        attrs = {item["key"]: item["value"]["stringValue"] for item in span["attributes"]}
        self.assertEqual(attrs["langfuse.observation.type"], "generation")
        self.assertEqual(attrs["langfuse.observation.input"], "Ship a release")
        self.assertEqual(attrs["langfuse.observation.output"], "Release notes are ready.")


if __name__ == "__main__":
    unittest.main()
