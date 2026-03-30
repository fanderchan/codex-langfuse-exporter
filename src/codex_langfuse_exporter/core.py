"""Core sync logic for Codex Langfuse Exporter."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:
    tomllib = None


def default_codex_root() -> Path:
    return Path.home() / ".codex"


DEFAULT_CODEX_ROOT = default_codex_root()
DEFAULT_CODEX_CONFIG = DEFAULT_CODEX_ROOT / "config.toml"
DEFAULT_CODEX_SESSIONS = DEFAULT_CODEX_ROOT / "sessions"
DEFAULT_LANGFUSE_ENVIRONMENT = "dev"
DEFAULT_TIMEOUT_SEC = 30


def parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def to_unix_nanos(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return str(int(dt.timestamp() * 1_000_000_000))


def stable_hex(seed: str, length: int) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:length]


def extract_text_parts(content: list[dict[str, Any]] | None) -> str:
    if not content:
        return ""
    texts: list[str] = []
    for part in content:
        text = part.get("text")
        if isinstance(text, str) and text:
            texts.append(text)
    return "\n\n".join(texts).strip()


def is_bootstrap_context(text: str) -> bool:
    return "# AGENTS.md instructions for " in text and "<environment_context>" in text


def attr(key: str, value: Any) -> dict[str, Any]:
    return {"key": key, "value": {"stringValue": str(value)}}


def derive_public_key(headers: dict[str, str]) -> str | None:
    auth_header = headers.get("Authorization", "")
    if not auth_header.startswith("Basic "):
        return None
    try:
        raw = base64.b64decode(auth_header.split(" ", 1)[1]).decode("utf-8")
    except Exception:
        return None
    return raw.split(":", 1)[0]


@dataclass
class HttpConfig:
    endpoint: str
    headers: dict[str, str]
    public_key: str | None = None


@dataclass
class TokenUsage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0

    def add(self, payload: dict[str, Any]) -> None:
        self.input_tokens += int(payload.get("input_tokens") or 0)
        self.cached_input_tokens += int(payload.get("cached_input_tokens") or 0)
        self.output_tokens += int(payload.get("output_tokens") or 0)
        self.reasoning_output_tokens += int(payload.get("reasoning_output_tokens") or 0)
        self.total_tokens += int(payload.get("total_tokens") or 0)

    def to_langfuse_usage(self) -> dict[str, int]:
        usage: dict[str, int] = {}
        input_cached = self.cached_input_tokens
        input_non_cached = max(self.input_tokens - input_cached, 0)
        output_reasoning = self.reasoning_output_tokens
        output_non_reasoning = max(self.output_tokens - output_reasoning, 0)

        if input_non_cached:
            usage["input"] = input_non_cached
        if input_cached:
            usage["input_cached_tokens"] = input_cached
        if output_non_reasoning:
            usage["output"] = output_non_reasoning
        if output_reasoning:
            usage["output_reasoning_tokens"] = output_reasoning
        if self.total_tokens:
            usage["total"] = self.total_tokens

        return usage


@dataclass
class TurnRecord:
    session_id: str
    turn_id: str
    model: str | None = None
    start_ts: datetime | None = None
    end_ts: datetime | None = None
    user_messages: list[str] = field(default_factory=list)
    assistant_messages: list[tuple[str, str | None]] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)

    def touch(self, ts: datetime | None) -> None:
        if ts is None:
            return
        if self.start_ts is None or ts < self.start_ts:
            self.start_ts = ts
        if self.end_ts is None or ts > self.end_ts:
            self.end_ts = ts

    def add_user(self, text: str) -> None:
        text = text.strip()
        if text and not is_bootstrap_context(text):
            self.user_messages.append(text)

    def add_assistant(self, text: str, phase: str | None) -> None:
        text = text.strip()
        if text:
            self.assistant_messages.append((text, phase))

    def has_payload(self) -> bool:
        return bool(self.user_messages or self.assistant_messages or self.usage.total_tokens)

    def input_payload(self) -> str:
        if not self.user_messages:
            return ""
        if len(self.user_messages) == 1:
            return self.user_messages[0]
        return json.dumps(
            [{"role": "user", "content": text} for text in self.user_messages],
            ensure_ascii=False,
        )

    def output_payload(self) -> str:
        finals = [text for text, phase in self.assistant_messages if phase == "final"]
        if finals:
            return finals[-1]
        if self.assistant_messages:
            return self.assistant_messages[-1][0]
        return ""

    def trace_name(self, include_prompt: bool = True) -> str:
        if include_prompt and self.user_messages:
            prompt = self.user_messages[-1].replace("\n", " ")
            return f"Codex Turn: {prompt[:80]}"
        return f"Codex Turn {self.turn_id}"

    def metadata_json(self) -> str:
        return json.dumps(
            {
                "source": "codex-session-backfill",
                "session_id": self.session_id,
                "turn_id": self.turn_id,
                "assistant_message_count": len(self.assistant_messages),
                "user_message_count": len(self.user_messages),
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    def state_key(self) -> str:
        return f"{self.session_id}:{self.turn_id}"

    def sync_fingerprint(
        self,
        include_prompt: bool = True,
        include_output: bool = True,
        include_usage: bool = True,
    ) -> str:
        payload = {
            "include_prompt": include_prompt,
            "include_output": include_output,
            "include_usage": include_usage,
            "model": self.model or "",
            "start_ts": self.start_ts.isoformat() if self.start_ts else "",
            "end_ts": self.end_ts.isoformat() if self.end_ts else "",
            "input": self.input_payload() if include_prompt else "",
            "output": self.output_payload() if include_output else "",
            "usage": self.usage.to_langfuse_usage() if include_usage else {},
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class SyncOptions:
    config: Path = DEFAULT_CODEX_CONFIG
    sessions_root: Path = DEFAULT_CODEX_SESSIONS
    days: int = 3
    limit: int = 30
    session_id: str | None = None
    dry_run: bool = False
    state_file: Path | None = None
    endpoint_override: str | None = None
    header_overrides: dict[str, str] = field(default_factory=dict)
    public_key_override: str | None = None
    langfuse_environment: str = DEFAULT_LANGFUSE_ENVIRONMENT
    include_prompt: bool = True
    include_output: bool = True
    include_usage: bool = True
    timeout_sec: int = DEFAULT_TIMEOUT_SEC


@dataclass
class SyncSummary:
    endpoint: str
    inspected_sessions: int
    eligible_turns: int
    turns_to_send: int
    dry_run: bool
    state_file: str | None
    include_prompt: bool
    include_output: bool
    include_usage: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "endpoint": self.endpoint,
            "inspected_sessions": self.inspected_sessions,
            "eligible_turns": self.eligible_turns,
            "turns_to_send": self.turns_to_send,
            "dry_run": self.dry_run,
            "state_file": self.state_file,
            "include_prompt": self.include_prompt,
            "include_output": self.include_output,
            "include_usage": self.include_usage,
        }


@dataclass
class PreparedSync:
    summary: SyncSummary
    payload: dict[str, Any]
    http_config: HttpConfig
    next_state: dict[str, str]


def load_otlp_config(
    path: Path,
    endpoint_override: str | None = None,
    header_overrides: dict[str, str] | None = None,
    public_key_override: str | None = None,
) -> HttpConfig:
    endpoint = None
    headers: dict[str, str] = {}

    if path.exists():
        if tomllib is not None:
            with path.open("rb") as fh:
                data = tomllib.load(fh)
            exporter = (
                (((data.get("otel") or {}).get("trace_exporter") or {}).get("otlp-http"))
                or {}
            )
            endpoint = exporter.get("endpoint")
            headers = dict(exporter.get("headers") or {})
        else:
            text = path.read_text(encoding="utf-8")
            endpoint_match = re.search(r'endpoint\s*=\s*"([^"]+)"', text)
            auth_match = re.search(r'Authorization\s*=\s*"([^"]+)"', text)
            ingestion_match = re.search(
                r'x-langfuse-ingestion-version\s*=\s*"([^"]+)"',
                text,
            )
            if endpoint_match:
                endpoint = endpoint_match.group(1)
            if auth_match:
                headers["Authorization"] = auth_match.group(1)
            if ingestion_match:
                headers["x-langfuse-ingestion-version"] = ingestion_match.group(1)
    elif not endpoint_override:
        raise FileNotFoundError(f"Codex config not found: {path}")

    if endpoint_override:
        endpoint = endpoint_override
    if header_overrides:
        headers.update(header_overrides)

    if not endpoint:
        raise ValueError(f"Missing otel.trace_exporter.otlp-http.endpoint in {path}")

    public_key = public_key_override or derive_public_key(headers)
    return HttpConfig(endpoint=endpoint, headers=headers, public_key=public_key)


def parse_session(session_path: Path) -> tuple[str, str | None, list[TurnRecord]]:
    session_id = session_path.stem.split("-")[-1]
    cli_version: str | None = None
    active_turn_id: str | None = None
    turns: dict[str, TurnRecord] = {}

    with session_path.open("r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts = parse_iso8601(entry.get("timestamp"))
            payload = entry.get("payload") or {}
            entry_type = entry.get("type")

            if entry_type == "session_meta":
                session_id = payload.get("id") or session_id
                cli_version = payload.get("cli_version")
                continue

            if entry_type == "event_msg" and payload.get("type") == "task_started":
                active_turn_id = payload.get("turn_id")
                if active_turn_id:
                    turn = turns.setdefault(
                        active_turn_id,
                        TurnRecord(session_id=session_id, turn_id=active_turn_id),
                    )
                    turn.touch(ts)
                continue

            if entry_type == "turn_context":
                active_turn_id = payload.get("turn_id") or active_turn_id
                if active_turn_id:
                    turn = turns.setdefault(
                        active_turn_id,
                        TurnRecord(session_id=session_id, turn_id=active_turn_id),
                    )
                    turn.touch(ts)
                    if isinstance(payload.get("model"), str):
                        turn.model = payload["model"]
                continue

            turn_id = payload.get("turn_id") if isinstance(payload, dict) else None
            turn_id = turn_id or active_turn_id
            if not turn_id:
                continue

            turn = turns.setdefault(turn_id, TurnRecord(session_id=session_id, turn_id=turn_id))
            turn.touch(ts)

            if entry_type == "response_item" and payload.get("type") == "message":
                text = extract_text_parts(payload.get("content"))
                role = payload.get("role")
                phase = payload.get("phase")
                if role == "user":
                    turn.add_user(text)
                elif role == "assistant":
                    turn.add_assistant(text, phase)
                continue

            if entry_type == "event_msg" and payload.get("type") == "token_count":
                info = payload.get("info") or {}
                last_usage = info.get("last_token_usage") or {}
                if isinstance(last_usage, dict):
                    turn.usage.add(last_usage)

    turn_records = [turn for turn in turns.values() if turn.has_payload()]
    turn_records.sort(
        key=lambda turn: (
            turn.start_ts or datetime.min.replace(tzinfo=timezone.utc),
            turn.end_ts or datetime.min.replace(tzinfo=timezone.utc),
            turn.turn_id,
        )
    )
    return session_id, cli_version, turn_records


def load_state(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}

    state: dict[str, str] = {}
    for key, value in data.items():
        if isinstance(key, str) and isinstance(value, str):
            state[key] = value
    return state


def save_state(path: Path | None, state: dict[str, str]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".{path.name}.tmp"
    tmp_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def build_payload(
    turns: list[TurnRecord],
    public_key: str | None,
    cli_version: str | None,
    langfuse_environment: str = DEFAULT_LANGFUSE_ENVIRONMENT,
    include_prompt: bool = True,
    include_output: bool = True,
    include_usage: bool = True,
) -> dict[str, Any]:
    spans: list[dict[str, Any]] = []
    scope_attributes: list[dict[str, Any]] = []
    if public_key:
        scope_attributes.append(attr("public_key", public_key))

    for turn in turns:
        model = turn.model or "gpt-5.4"
        trace_id = stable_hex(f"codex-trace:{turn.session_id}:{turn.turn_id}", 32)
        span_id = stable_hex(f"codex-span:{turn.session_id}:{turn.turn_id}", 16)
        start_ts = turn.start_ts or datetime.now(timezone.utc)
        end_ts = turn.end_ts or start_ts
        trace_input = turn.input_payload()
        trace_output = turn.output_payload()
        usage = turn.usage.to_langfuse_usage() if include_usage else {}

        attributes = [
            attr("langfuse.trace.name", turn.trace_name(include_prompt=include_prompt)),
            attr("langfuse.trace.metadata", turn.metadata_json()),
            attr("session.id", turn.session_id),
            attr("langfuse.observation.type", "generation"),
            attr("langfuse.observation.model.name", model),
            attr("langfuse.observation.metadata", turn.metadata_json()),
        ]
        if include_prompt:
            attributes.extend(
                [
                    attr("langfuse.trace.input", trace_input),
                    attr("langfuse.observation.input", trace_input),
                ]
            )
        if include_output:
            attributes.extend(
                [
                    attr("langfuse.trace.output", trace_output),
                    attr("langfuse.observation.output", trace_output),
                ]
            )
        if usage:
            attributes.append(
                attr(
                    "langfuse.observation.usage_details",
                    json.dumps(usage, ensure_ascii=False, sort_keys=True),
                )
            )

        spans.append(
            {
                "traceId": trace_id,
                "spanId": span_id,
                "name": "codex.turn.backfill",
                "kind": 1,
                "startTimeUnixNano": to_unix_nanos(start_ts),
                "endTimeUnixNano": to_unix_nanos(end_ts),
                "attributes": attributes,
                "status": {},
            }
        )

    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        attr("service.name", "codex-langfuse-exporter"),
                        attr("service.version", cli_version or "unknown"),
                        attr("langfuse.environment", langfuse_environment),
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {
                            "name": "codex-langfuse-exporter",
                            "version": "0.1.0",
                            "attributes": scope_attributes,
                        },
                        "spans": spans,
                    }
                ],
            }
        ]
    }


def post_payload(
    endpoint: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    user_agent: str = "codex-langfuse-exporter/0.1.0",
) -> tuple[int, str]:
    request_headers = {
        "Content-Type": "application/json",
        "User-Agent": user_agent,
    }
    request_headers.update(headers)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(endpoint, data=data, headers=request_headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        body = response.read().decode("utf-8", errors="replace")
        return response.getcode(), body


def prepare_sync(options: SyncOptions) -> PreparedSync:
    http_config = load_otlp_config(
        options.config,
        endpoint_override=options.endpoint_override,
        header_overrides=options.header_overrides,
        public_key_override=options.public_key_override,
    )
    previous_state = load_state(options.state_file)
    next_state = dict(previous_state)

    cutoff = datetime.now(timezone.utc) - timedelta(days=options.days)
    session_files = sorted(options.sessions_root.rglob("*.jsonl"), reverse=True)

    selected_turns: list[TurnRecord] = []
    cli_version: str | None = None
    inspected = 0
    eligible_turns = 0

    for session_path in session_files:
        if inspected >= options.limit:
            break

        session_id, discovered_cli_version, turns = parse_session(session_path)
        if options.session_id and session_id != options.session_id:
            continue

        inspected += 1
        cli_version = cli_version or discovered_cli_version

        for turn in turns:
            if turn.end_ts and turn.end_ts < cutoff:
                continue
            eligible_turns += 1
            if options.state_file:
                fingerprint = turn.sync_fingerprint(
                    include_prompt=options.include_prompt,
                    include_output=options.include_output,
                    include_usage=options.include_usage,
                )
                if previous_state.get(turn.state_key()) == fingerprint:
                    continue
                next_state[turn.state_key()] = fingerprint
            selected_turns.append(turn)

    payload = build_payload(
        selected_turns,
        public_key=http_config.public_key,
        cli_version=cli_version,
        langfuse_environment=options.langfuse_environment,
        include_prompt=options.include_prompt,
        include_output=options.include_output,
        include_usage=options.include_usage,
    )
    summary = SyncSummary(
        endpoint=http_config.endpoint,
        inspected_sessions=inspected,
        eligible_turns=eligible_turns,
        turns_to_send=len(selected_turns),
        dry_run=options.dry_run,
        state_file=str(options.state_file) if options.state_file else None,
        include_prompt=options.include_prompt,
        include_output=options.include_output,
        include_usage=options.include_usage,
    )
    return PreparedSync(
        summary=summary,
        payload=payload,
        http_config=http_config,
        next_state=next_state,
    )
