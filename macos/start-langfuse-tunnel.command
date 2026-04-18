#!/bin/bash
set -euo pipefail

TARGET_HOST="${TARGET_HOST:-192.168.199.176}"
SSH_TARGET="${SSH_TARGET:-root@176.dbops.cn}"
LOCAL_PORT="${LOCAL_PORT:-3000}"
REMOTE_PORT="${REMOTE_PORT:-3000}"
KEY_FILE="${KEY_FILE:-${HOME}/.ssh/id_ed25519}"
OPEN_BROWSER="${OPEN_BROWSER:-1}"

if [[ ! -f "${KEY_FILE}" ]]; then
  echo "SSH key not found: ${KEY_FILE}"
  exit 1
fi

if [[ "${OPEN_BROWSER}" == "1" ]]; then
  open "http://127.0.0.1:${LOCAL_PORT}" >/dev/null 2>&1 || true
fi

echo "Starting SSH tunnel..."
echo "Local URL: http://127.0.0.1:${LOCAL_PORT}"
echo "SSH target: ${SSH_TARGET}"
echo "Forwarding: ${LOCAL_PORT} -> ${TARGET_HOST}:${REMOTE_PORT}"
echo "Press Ctrl+C to stop."

exec ssh -i "${KEY_FILE}" -N -L "${LOCAL_PORT}:${TARGET_HOST}:${REMOTE_PORT}" "${SSH_TARGET}"
