#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LABEL="${LABEL:-com.fander.codex-langfuse-exporter}"
PLIST_PATH="${HOME}/Library/LaunchAgents/${LABEL}.plist"
START_INTERVAL="${START_INTERVAL:-600}"

mkdir -p "${HOME}/Library/LaunchAgents" "${REPO_ROOT}/state"

cat > "${PLIST_PATH}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${REPO_ROOT}/macos/run-codex-langfuse-exporter.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${REPO_ROOT}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>${START_INTERVAL}</integer>
  <key>StandardOutPath</key>
  <string>${REPO_ROOT}/state/launchd.stdout.log</string>
  <key>StandardErrorPath</key>
  <string>${REPO_ROOT}/state/launchd.stderr.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)" "${PLIST_PATH}" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "${PLIST_PATH}"
launchctl enable "gui/$(id -u)/${LABEL}" >/dev/null 2>&1 || true

echo "Installed launch agent: ${PLIST_PATH}"
echo "Cadence: every ${START_INTERVAL} seconds"
echo "Logs: ${REPO_ROOT}/state/launchd.stdout.log and ${REPO_ROOT}/state/launchd.stderr.log"
