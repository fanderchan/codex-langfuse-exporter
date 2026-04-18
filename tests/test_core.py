from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TESTS_ROOT = Path(__file__).resolve().parent
SRC_ROOT = TESTS_ROOT.parent / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from codex_langfuse_exporter.cli import build_parser
from codex_langfuse_exporter.cli import main
from codex_langfuse_exporter.core import DEFAULT_CODEX_CONFIG
from codex_langfuse_exporter.core import DEFAULT_CODEX_SESSIONS
from codex_langfuse_exporter.core import HttpConfig
from codex_langfuse_exporter.core import PreparedSync
from codex_langfuse_exporter.core import SyncSummary
from codex_langfuse_exporter.core import build_payload
from codex_langfuse_exporter.core import load_otlp_config
from codex_langfuse_exporter.core import parse_session


def decode_attr_value(raw: dict[str, object]) -> object:
    if "stringValue" in raw:
        return raw["stringValue"]
    if "intValue" in raw:
        return int(str(raw["intValue"]))
    if "doubleValue" in raw:
        return raw["doubleValue"]
    if "boolValue" in raw:
        return raw["boolValue"]
    raise AssertionError(f"Unsupported attribute value: {raw!r}")


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
        self.assertEqual(
            decode_attr_value(scope_span["scope"]["attributes"][0]["value"]),
            "pk-lf-test",
        )

        span = scope_span["spans"][0]
        self.assertEqual(span["name"], "codex.turn.backfill")
        attrs = {item["key"]: decode_attr_value(item["value"]) for item in span["attributes"]}
        self.assertEqual(attrs["langfuse.observation.type"], "generation")
        self.assertEqual(attrs["langfuse.observation.input"], "Ship a release")
        self.assertEqual(attrs["langfuse.observation.output"], "Release notes are ready.")
        self.assertEqual(attrs["gen_ai.request.model"], "gpt-5.4")
        self.assertEqual(attrs["gen_ai.response.model"], "gpt-5.4")

    def test_build_payload_can_export_usage_only_without_text_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            session_path = Path(tmpdir) / "session-foo.jsonl"
            lines = [
                {
                    "type": "session_meta",
                    "timestamp": "2026-03-30T01:00:00Z",
                    "payload": {"id": "sess-3", "cli_version": "0.3.0"},
                },
                {
                    "type": "event_msg",
                    "timestamp": "2026-03-30T01:00:01Z",
                    "payload": {"type": "task_started", "turn_id": "turn-3"},
                },
                {
                    "type": "turn_context",
                    "timestamp": "2026-03-30T01:00:02Z",
                    "payload": {"turn_id": "turn-3", "model": "gpt-5.4"},
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-03-30T01:00:03Z",
                    "payload": {
                        "turn_id": "turn-3",
                        "type": "message",
                        "role": "user",
                        "content": [{"text": "Do not leak this prompt"}],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-03-30T01:00:04Z",
                    "payload": {
                        "turn_id": "turn-3",
                        "type": "message",
                        "role": "assistant",
                        "phase": "final",
                        "content": [{"text": "Do not leak this output either"}],
                    },
                },
                {
                    "type": "event_msg",
                    "timestamp": "2026-03-30T01:00:05Z",
                    "payload": {
                        "turn_id": "turn-3",
                        "type": "token_count",
                        "info": {
                            "last_token_usage": {
                                "input_tokens": 50,
                                "cached_input_tokens": 10,
                                "output_tokens": 12,
                                "reasoning_output_tokens": 2,
                                "total_tokens": 62,
                            }
                        },
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
            cli_version="0.3.0",
            langfuse_environment="prod",
            include_prompt=False,
            include_output=False,
            include_usage=True,
        )

        span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attrs = {item["key"]: decode_attr_value(item["value"]) for item in span["attributes"]}
        self.assertEqual(attrs["langfuse.trace.name"], "Codex Turn turn-3")
        self.assertNotIn("langfuse.trace.input", attrs)
        self.assertNotIn("langfuse.trace.output", attrs)
        self.assertNotIn("langfuse.observation.input", attrs)
        self.assertNotIn("langfuse.observation.output", attrs)
        self.assertEqual(
            json.loads(attrs["langfuse.observation.usage_details"]),
            {
                "input": 40,
                "input_cached_tokens": 10,
                "output": 10,
                "output_reasoning_tokens": 2,
                "total": 62,
            },
        )
        self.assertEqual(attrs["gen_ai.usage.input_tokens"], 50)
        self.assertEqual(attrs["gen_ai.usage.output_tokens"], 12)

    def test_sync_fingerprint_changes_when_export_selection_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            session_path = Path(tmpdir) / "session-bar.jsonl"
            lines = [
                {
                    "type": "session_meta",
                    "timestamp": "2026-03-30T01:00:00Z",
                    "payload": {"id": "sess-4", "cli_version": "0.4.0"},
                },
                {
                    "type": "event_msg",
                    "timestamp": "2026-03-30T01:00:01Z",
                    "payload": {"type": "task_started", "turn_id": "turn-4"},
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-03-30T01:00:02Z",
                    "payload": {
                        "turn_id": "turn-4",
                        "type": "message",
                        "role": "user",
                        "content": [{"text": "private prompt"}],
                    },
                },
            ]
            session_path.write_text(
                "".join(json.dumps(line) + "\n" for line in lines),
                encoding="utf-8",
            )
            _, _, turns = parse_session(session_path)

        self.assertEqual(len(turns), 1)
        self.assertNotEqual(
            turns[0].sync_fingerprint(),
            turns[0].sync_fingerprint(include_prompt=False, include_output=False),
        )


class ConfigDefaultsTests(unittest.TestCase):
    def test_default_codex_paths_use_user_home_directory(self) -> None:
        codex_root = Path.home() / ".codex"
        self.assertEqual(DEFAULT_CODEX_CONFIG, codex_root / "config.toml")
        self.assertEqual(DEFAULT_CODEX_SESSIONS, codex_root / "sessions")

    def test_env_can_supply_otlp_config_when_codex_config_has_no_otel(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text('model = "gpt-5.4"\n', encoding="utf-8")

            with mock.patch.dict(
                "os.environ",
                {
                    "CODEX_LANGFUSE_ENDPOINT": "http://127.0.0.1:3000/api/public/otel/v1/traces",
                    "CODEX_LANGFUSE_PUBLIC_KEY": "pk-lf-test",
                    "CODEX_LANGFUSE_SECRET_KEY": "sk-lf-test",
                    "CODEX_LANGFUSE_INGESTION_VERSION": "4",
                },
                clear=False,
            ):
                http_config = load_otlp_config(config_path)

        self.assertEqual(
            http_config.endpoint,
            "http://127.0.0.1:3000/api/public/otel/v1/traces",
        )
        self.assertEqual(http_config.headers["x-langfuse-ingestion-version"], "4")
        self.assertTrue(http_config.headers["Authorization"].startswith("Basic "))
        self.assertEqual(http_config.public_key, "pk-lf-test")


class CliTests(unittest.TestCase):
    def test_cli_supports_disabling_prompt_and_output(self) -> None:
        args = build_parser().parse_args(["--no-prompt", "--no-output"])
        self.assertFalse(args.prompt)
        self.assertFalse(args.output)
        self.assertTrue(args.usage)

    def test_cli_accepts_log_file_argument(self) -> None:
        args = build_parser().parse_args(["--log-file", "state/task.log"])
        self.assertEqual(args.log_file, Path("state/task.log"))

    def test_main_writes_log_file_for_scheduled_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "scheduled-task.log"
            prepared = PreparedSync(
                summary=SyncSummary(
                    endpoint="https://example.com/otlp",
                    inspected_sessions=2,
                    eligible_turns=3,
                    turns_to_send=1,
                    dry_run=False,
                    state_file=str(Path(tmpdir) / "state.json"),
                    include_prompt=False,
                    include_output=False,
                    include_usage=True,
                ),
                payload={"resourceSpans": []},
                http_config=HttpConfig(
                    endpoint="https://example.com/otlp",
                    headers={},
                    public_key="pk-test",
                ),
                next_state={"turn-1": "fingerprint"},
            )

            with mock.patch(
                "codex_langfuse_exporter.cli.prepare_sync",
                return_value=prepared,
            ), mock.patch(
                "codex_langfuse_exporter.cli.post_payload",
                return_value=(200, "ok"),
            ), mock.patch(
                "codex_langfuse_exporter.cli.save_state",
            ) as save_state:
                exit_code = main(["--log-file", str(log_path)])

            self.assertEqual(exit_code, 0)
            save_state.assert_called_once_with(None, {"turn-1": "fingerprint"})

            log_text = log_path.read_text(encoding="utf-8")
            self.assertIn("Starting sync:", log_text)
            self.assertIn("Prepared sync summary:", log_text)
            self.assertIn("Langfuse response: HTTP 200 ok", log_text)


if __name__ == "__main__":
    unittest.main()
