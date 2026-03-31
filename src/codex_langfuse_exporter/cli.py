"""CLI entrypoint for Codex Langfuse Exporter."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.error
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import __version__
from .core import DEFAULT_CODEX_CONFIG
from .core import DEFAULT_CODEX_SESSIONS
from .core import DEFAULT_LANGFUSE_ENVIRONMENT
from .core import DEFAULT_TIMEOUT_SEC
from .core import SyncOptions
from .core import post_payload
from .core import prepare_sync
from .core import save_state

LOGGER_NAME = "codex_langfuse_exporter"
LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 3


def parse_header_arg(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError(
            f"invalid header {value!r}: expected NAME=VALUE",
        )
    name, header_value = value.split("=", 1)
    name = name.strip()
    if not name:
        raise argparse.ArgumentTypeError(
            f"invalid header {value!r}: missing header name",
        )
    return name, header_value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-langfuse-exporter",
        description="Sync local Codex sessions into Langfuse as generation observations.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CODEX_CONFIG,
        help="Path to Codex config.toml",
    )
    parser.add_argument(
        "--sessions-root",
        type=Path,
        default=DEFAULT_CODEX_SESSIONS,
        help="Directory containing Codex session JSONL files",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=3,
        help="Only sync turns newer than N days",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=30,
        help="Maximum number of session files to inspect",
    )
    parser.add_argument(
        "--session-id",
        help="Only sync one Codex session id",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan without sending data to Langfuse",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        help="Optional JSON state file used to skip unchanged turns across runs",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        help="Optional rotating log file path, useful for background scheduled tasks",
    )
    parser.add_argument(
        "--endpoint",
        help="Override the Langfuse OTLP endpoint instead of reading it from Codex config",
    )
    parser.add_argument(
        "--header",
        dest="headers",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Add or override an HTTP header for the OTLP request",
    )
    parser.add_argument(
        "--public-key",
        help="Override the Langfuse public key stored in OTLP scope attributes",
    )
    parser.add_argument(
        "--langfuse-environment",
        default=DEFAULT_LANGFUSE_ENVIRONMENT,
        help="Value to emit as langfuse.environment (default: %(default)s)",
    )
    parser.add_argument(
        "--prompt",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include prompt/user input text in exported Langfuse fields (default: enabled)",
    )
    parser.add_argument(
        "--output",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include final assistant output text in exported Langfuse fields (default: enabled)",
    )
    parser.add_argument(
        "--usage",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include token usage details in exported Langfuse fields (default: enabled)",
    )
    parser.add_argument(
        "--timeout-sec",
        type=int,
        default=DEFAULT_TIMEOUT_SEC,
        help="HTTP timeout in seconds when posting to Langfuse",
    )
    return parser


def emit_console(message: str, *, stderr: bool = False) -> None:
    stream = sys.stderr if stderr else sys.stdout
    if stream is None:
        return
    try:
        print(message, file=stream, flush=True)
    except Exception:
        return


def configure_logger(log_file: Path | None) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    if log_file is None:
        logger.addHandler(logging.NullHandler())
        return logger

    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_file,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


def close_logger(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        try:
            handler.flush()
        except Exception:
            pass
        logger.removeHandler(handler)
        handler.close()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not (args.prompt or args.output or args.usage):
        parser.error("at least one of --prompt, --output, or --usage must be enabled")

    try:
        logger = configure_logger(args.log_file)
    except Exception as exc:
        emit_console(f"Failed to initialize log file: {exc}", stderr=True)
        return 1

    try:
        logger.info(
            "Starting sync: days=%s limit=%s state_file=%s log_file=%s prompt=%s output=%s usage=%s dry_run=%s",
            args.days,
            args.limit,
            args.state_file,
            args.log_file,
            args.prompt,
            args.output,
            args.usage,
            args.dry_run,
        )

        header_overrides = dict(parse_header_arg(raw) for raw in args.headers)
        options = SyncOptions(
            config=args.config,
            sessions_root=args.sessions_root,
            days=args.days,
            limit=args.limit,
            session_id=args.session_id,
            dry_run=args.dry_run,
            state_file=args.state_file,
            endpoint_override=args.endpoint,
            header_overrides=header_overrides,
            public_key_override=args.public_key,
            langfuse_environment=args.langfuse_environment,
            include_prompt=args.prompt,
            include_output=args.output,
            include_usage=args.usage,
            timeout_sec=args.timeout_sec,
        )

        try:
            prepared = prepare_sync(options)
        except Exception as exc:
            logger.exception("Failed to prepare sync")
            emit_console(f"Failed to prepare sync: {exc}", stderr=True)
            return 1

        summary_json = json.dumps(prepared.summary.to_dict(), ensure_ascii=False)
        logger.info("Prepared sync summary: %s", summary_json)
        emit_console(summary_json)

        if prepared.summary.turns_to_send == 0:
            logger.info("No new turns to sync.")
            emit_console("No new turns to sync.")
            return 0

        if args.dry_run:
            logger.info("Dry run prepared payload with %s spans.", prepared.summary.turns_to_send)
            emit_console(json.dumps(prepared.payload, ensure_ascii=False, indent=2)[:5000])
            return 0

        try:
            status, body = post_payload(
                prepared.http_config.endpoint,
                prepared.http_config.headers,
                prepared.payload,
                timeout_sec=options.timeout_sec,
                user_agent=f"codex-langfuse-exporter/{__version__}",
            )
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            logger.error("HTTP %s: %s", exc.code, error_body)
            emit_console(f"HTTP {exc.code}: {error_body}", stderr=True)
            return 2
        except Exception as exc:
            logger.exception("Failed to send payload")
            emit_console(f"Failed to send payload: {exc}", stderr=True)
            return 3

        save_state(options.state_file, prepared.next_state)
        logger.info("Langfuse response: HTTP %s %s", status, body[:1000])
        emit_console(f"Langfuse response: HTTP {status} {body[:1000]}")
        return 0
    finally:
        close_logger(logger)
