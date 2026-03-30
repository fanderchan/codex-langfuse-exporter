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

`prompt` in this project means the user input text for a Codex turn.
`output` means the final assistant reply text for that turn.

## What it does

- Reads Codex session files from the current user's `.codex/sessions`
- Reconstructs one observation per Codex turn
- Extracts turn input, final assistant output, and token usage
- Can export prompt, output, and usage independently for privacy-sensitive setups
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
cd codex-langfuse-exporter
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

### 2. Check the detected config

By default the exporter reads Langfuse OTLP settings from the current user's
Codex config file.

```bash
codex-langfuse-exporter --dry-run
```

### 3. Sync recent sessions

```bash
codex-langfuse-exporter --days 3 --limit 30
```

## Enable Codex OTEL

The exporter reads the Langfuse OTLP endpoint and headers from Codex's
`config.toml` by default. Configure Codex OTEL first if you want the exporter
to auto-discover where to send data.

Example `~/.codex/config.toml` on Linux/macOS, or
`%USERPROFILE%\.codex\config.toml` on Windows:

```toml
[otel]
environment = "dev"
log_user_prompt = true

trace_exporter = { otlp-http = {
  endpoint = "http://127.0.0.1:3000/api/public/otel/v1/traces",
  protocol = "binary",
  headers = {
    Authorization = "Basic <base64(public_key:secret_key)>",
    x-langfuse-ingestion-version = "4"
  }
}}
```

`Authorization` is HTTP Basic auth built from your Langfuse public key and
secret key in the form `public_key:secret_key`, then Base64-encoded.

Generate it on Linux/macOS:

```bash
printf '%s' 'pk-lf-...:sk-lf-...' | base64
```

Generate it on Windows PowerShell:

```powershell
[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("pk-lf-...:sk-lf-..."))
```

If you only want the exporter to send token usage and not prompt or output
text, run the exporter with `--no-prompt --no-output`. If you also want Codex's
native OTEL spans to avoid user prompt text, set `log_user_prompt = false`.

## Installation modes

### Editable install

Best when you are developing or iterating on the exporter.

```bash
pip install -e .
```

### Direct script execution

Best when you want to keep the existing local workflow unchanged.

```bash
python3 /path/to/codex-langfuse-exporter/codex_langfuse_sync.py --days 1 --limit 50
```

The legacy script stays supported and simply dispatches into the packaged CLI.

## Configuration

### Default Codex paths

- Linux/macOS config: `~/.codex/config.toml`
- Linux/macOS sessions: `~/.codex/sessions`
- Windows config: `%USERPROFILE%\.codex\config.toml`
- Windows sessions: `%USERPROFILE%\.codex\sessions`

Override them with:

```bash
codex-langfuse-exporter \
  --config /path/to/config.toml \
  --sessions-root /path/to/sessions
```

### Privacy controls

All three export fields are enabled by default:

- `--prompt`: include user input text
- `--output`: include final assistant output text
- `--usage`: include token usage

Disable any field with the matching `--no-...` flag. For example, export only
token usage without sending prompt or output text:

```bash
codex-langfuse-exporter \
  --days 3 \
  --no-prompt \
  --no-output
```

These flags affect what new payloads send to Langfuse. They do not remove text
that was already ingested by an earlier export.

### Override the OTLP endpoint manually

Useful when you want to test against another Langfuse instance without changing
Codex config.

```bash
codex-langfuse-exporter \
  --endpoint https://langfuse.example.com/api/public/otel/v1/traces \
  --header 'Authorization=Basic ...' \
  --header 'x-langfuse-ingestion-version=4'
```

### Incremental sync

Use a state file to skip unchanged turns:

```bash
codex-langfuse-exporter \
  --days 1 \
  --limit 50 \
  --state-file /var/lib/codex-langfuse-exporter/codex_langfuse_sync_state.json
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
  --prompt / --no-prompt
  --output / --no-output
  --usage / --no-usage
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

Linux only. Windows users should run the CLI directly or schedule it with Task
Scheduler.

Example unit files live in [`systemd/`](./systemd). Review the paths before
installing them.

```bash
sudo install -m 0644 systemd/codex-langfuse-sync.service /etc/systemd/system/codex-langfuse-sync.service
sudo install -m 0644 systemd/codex-langfuse-sync.timer /etc/systemd/system/codex-langfuse-sync.timer
sudo systemctl daemon-reload
sudo systemctl enable --now codex-langfuse-sync.timer
```

## Windows Task Scheduler

If you use Codex on Windows, schedule the exporter with Task Scheduler instead
of `systemd`. A virtualenv is optional; using a global Python 3.14 install is
fine.

The repository includes a one-click setup script at
[`windows/install-codex-langfuse-task.ps1`](./windows/install-codex-langfuse-task.ps1).
Edit the variables at the top of that file first:

- `PythonPath`: full path to your global Python, for example `C:\Python314\python.exe`
- `ProjectDir`: local checkout path, for example `C:\work\codex-langfuse-exporter`
- `StateFilePath`: where incremental sync state should be stored
- `ExporterArgs`: exporter CLI flags, for example `--no-prompt --no-output`
- `StartTime` and `RepeatMinutes`: schedule settings

Then run it from PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\install-codex-langfuse-task.ps1
```

The script creates or replaces a scheduled task for the current Windows user.
By default it uses `LogonType Interactive`, so the task runs while that user is
logged in and does not require storing the account password inside the script.

Manual equivalent command:

```powershell
C:\Python314\python.exe C:\path\to\codex-langfuse-exporter\codex_langfuse_sync.py --days 1 --no-prompt --no-output
```

Recommended Task Scheduler fields:

- `Program/script`: `C:\Python314\python.exe`
- `Add arguments`: `C:\path\to\codex-langfuse-exporter\codex_langfuse_sync.py --days 1 --no-prompt --no-output`
- `Start in`: `C:\path\to\codex-langfuse-exporter`

Use the full path to `python.exe` rather than `py` so scheduled runs do not
depend on PATH or launcher behavior.

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
- Use `--no-prompt` and/or `--no-output` if you only want to send token usage.
- It forwards the enabled fields to the configured Langfuse OTLP endpoint.
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
