#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

ENV_FILE=""
for candidate in \
  "${REPO_ROOT}/macos/codex-langfuse-exporter.env" \
  "${HOME}/.config/codex-langfuse-exporter.env"
do
  if [[ -f "${candidate}" ]]; then
    ENV_FILE="${candidate}"
    break
  fi
done

if [[ -n "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "${ENV_FILE}"
  set +a
fi

mkdir -p "${REPO_ROOT}/state"

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "${PYTHON_BIN}" ]]; then
  if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
  else
    PYTHON_BIN="$(command -v python3)"
  fi
fi

if [[ -z "${PYTHON_BIN}" ]]; then
  echo "python3 was not found."
  exit 1
fi

export CODEX_LANGFUSE_ENDPOINT="${CODEX_LANGFUSE_ENDPOINT:-http://127.0.0.1:3000/api/public/otel/v1/traces}"
export CODEX_LANGFUSE_INGESTION_VERSION="${CODEX_LANGFUSE_INGESTION_VERSION:-4}"

if [[ -n "${LANGFUSE_PUBLIC_KEY:-}" && -z "${CODEX_LANGFUSE_PUBLIC_KEY:-}" ]]; then
  export CODEX_LANGFUSE_PUBLIC_KEY="${LANGFUSE_PUBLIC_KEY}"
fi
if [[ -n "${LANGFUSE_SECRET_KEY:-}" && -z "${CODEX_LANGFUSE_SECRET_KEY:-}" ]]; then
  export CODEX_LANGFUSE_SECRET_KEY="${LANGFUSE_SECRET_KEY}"
fi

if [[ -z "${CODEX_LANGFUSE_AUTHORIZATION:-}" && -n "${CODEX_LANGFUSE_PUBLIC_KEY:-}" && -n "${CODEX_LANGFUSE_SECRET_KEY:-}" ]]; then
  AUTH_B64="$(printf '%s' "${CODEX_LANGFUSE_PUBLIC_KEY}:${CODEX_LANGFUSE_SECRET_KEY}" | base64)"
  export CODEX_LANGFUSE_AUTHORIZATION="Basic ${AUTH_B64}"
fi

CONFIG_HAS_OTEL=0
if grep -q '^\[otel\]' "${HOME}/.codex/config.toml" 2>/dev/null; then
  CONFIG_HAS_OTEL=1
fi

if [[ "${CONFIG_HAS_OTEL}" -eq 0 && -z "${CODEX_LANGFUSE_AUTHORIZATION:-}" ]]; then
  echo "No usable Langfuse auth was found."
  echo "Add CODEX_LANGFUSE_SECRET_KEY to macos/codex-langfuse-exporter.env or ~/.config/codex-langfuse-exporter.env."
  exit 1
fi

STATE_FILE="${STATE_FILE:-${REPO_ROOT}/state/state.json}"
LOG_FILE="${LOG_FILE:-${REPO_ROOT}/state/scheduled-task.log}"
EXPORTER_ARGS="${EXPORTER_ARGS:---days 1 --limit 50 --no-prompt --no-output}"

read -r -a EXTRA_ARGS <<< "${EXPORTER_ARGS}"

cd "${REPO_ROOT}"
exec "${PYTHON_BIN}" "${REPO_ROOT}/codex_langfuse_sync.py" \
  --state-file "${STATE_FILE}" \
  --log-file "${LOG_FILE}" \
  "${EXTRA_ARGS[@]}" \
  "$@"
