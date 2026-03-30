# Codex Langfuse Exporter

[![CI](https://github.com/fanderchan/codex-langfuse-exporter/actions/workflows/ci.yml/badge.svg)](https://github.com/fanderchan/codex-langfuse-exporter/actions/workflows/ci.yml)

English | [简体中文](./README.zh-CN.md)

Backfill Codex local session data into Langfuse as synthetic `generation`
observations.

This project is for teams running Codex locally while sending traces to
Langfuse. Codex already emits OTEL spans, but those spans may not expose
Langfuse-friendly prompt, output, and token usage fields. This exporter reads
the local Codex session JSONL files and posts stable synthetic observations so
those fields become visible in Langfuse.

## What it does

- Reads Codex session files from `~/.codex/sessions`
- Reconstructs one observation per Codex turn
- Extracts turn input, final assistant output, and token usage
- Skips the bootstrap AGENTS and environment preamble on purpose
- Uses stable trace and span ids so repeated syncs update the same backfilled
  observations
- Supports incremental sync via a state file
- Can run ad hoc, from cron, or from the included systemd timer

## What it does not do

- It does not modify Codex itself.
- It does not modify Langfuse.
- It does not reconstruct hidden internal model rounds that are not present in
  local Codex session files.
- It does not replace Codex native OTEL spans. It complements them.

## Quick start

### 1. Create a virtualenv

```bash
cd exporter
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

### 2. Check the detected config

By default the exporter reads Langfuse OTLP settings from
`/root/.codex/config.toml`.

```bash
codex-langfuse-exporter --dry-run
```

### 3. Sync recent sessions

```bash
codex-langfuse-exporter --days 3 --limit 30
```

## Installation modes

### Editable install

Best when you are developing or iterating on the exporter.

```bash
pip install -e .
```

### Direct script execution

Best when you want to keep the existing local workflow unchanged.

```bash
python3 /path/to/exporter/codex_langfuse_sync.py --days 1 --limit 50
```

The legacy script stays supported and simply dispatches into the packaged CLI.

## Configuration

### Default Codex paths

- Codex config: `/root/.codex/config.toml`
- Codex sessions: `/root/.codex/sessions`

Override them with:

```bash
codex-langfuse-exporter \
  --config /path/to/config.toml \
  --sessions-root /path/to/sessions
```

### Override the OTLP endpoint manually

Useful when you want to test against another Langfuse instance without changing
Codex config.

```bash
codex-langfuse-exporter \
  --endpoint https://langfuse.example.com/api/public/otel \
  --header 'Authorization=Basic ...' \
  --header 'x-langfuse-ingestion-version=2'
```

### Incremental sync

Use a state file to skip unchanged turns:

```bash
codex-langfuse-exporter \
  --days 1 \
  --limit 50 \
  --state-file /var/lib/codex-langfuse-exporter/state.json
```

### Sync a single session

```bash
codex-langfuse-exporter \
  --session-id 019d3d85-2065-7dc0-b58c-5e31d9c80368
```

## CLI reference

```text
usage: codex-langfuse-exporter [options]

Core options:
  --config PATH
  --sessions-root PATH
  --days N
  --limit N
  --session-id ID
  --state-file PATH
  --dry-run

OTLP options:
  --endpoint URL
  --header NAME=VALUE
  --public-key KEY
  --langfuse-environment NAME
  --timeout-sec N
```

Run `codex-langfuse-exporter --help` for the full option list.

## systemd timer

Example unit files live in [`systemd/`](./systemd). Review the paths before
installing them.

```bash
sudo install -m 0644 systemd/codex-langfuse-sync.service /etc/systemd/system/codex-langfuse-sync.service
sudo install -m 0644 systemd/codex-langfuse-sync.timer /etc/systemd/system/codex-langfuse-sync.timer
sudo systemctl daemon-reload
sudo systemctl enable --now codex-langfuse-sync.timer
```

## How the exporter maps data

For each Codex turn, the exporter emits one synthetic Langfuse
`generation` observation with:

- `langfuse.trace.name`
- `langfuse.trace.input`
- `langfuse.trace.output`
- `langfuse.observation.type = generation`
- `langfuse.observation.input`
- `langfuse.observation.output`
- `langfuse.observation.usage_details`

Trace and span ids are stable per `session_id + turn_id`, which makes repeated
syncs idempotent from the exporter's point of view.

## Privacy and security notes

- The exporter reads local Codex session files, which may contain sensitive
  prompts or outputs.
- It forwards those fields to the configured Langfuse OTLP endpoint.
- Review your Codex retention policy, filesystem permissions, and Langfuse
  deployment before enabling unattended sync.

## Development

Run the test suite:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Run a dry run against local files:

```bash
python3 codex_langfuse_sync.py --dry-run
```

## Release checklist

1. Update the version in `pyproject.toml` and `src/codex_langfuse_exporter/__init__.py`
2. Update `CHANGELOG.md`
3. Run the unit tests
4. Verify `--dry-run` against a real Codex session directory
5. Tag and publish

## License

MIT. See [`LICENSE`](./LICENSE).
