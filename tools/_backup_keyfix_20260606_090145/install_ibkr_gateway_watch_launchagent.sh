#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="${LABEL:-com.ouroboros.ibkr.gateway.watch}"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3)}"
INTERVAL_SEC="${INTERVAL_SEC:-300}"
TIMEOUT_SEC="${TIMEOUT_SEC:-15}"
COOLDOWN_HOURS="${COOLDOWN_HOURS:-6}"
VM_MODE="${VM_MODE:-1}"
VM_HOST="${VM_HOST:-161.33.26.35}"
VM_USER="${VM_USER:-ubuntu}"
VM_KEY="${VM_KEY:-/Users/tani/Downloads/ssh-key-2026-03-04-4.key}"

mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/review_out"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>WorkingDirectory</key>
  <string>${ROOT}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON_BIN}</string>
    <string>${ROOT}/tools/ibkr_gateway_watch.py</string>
    <string>--timeout-sec</string>
    <string>${TIMEOUT_SEC}</string>
    <string>--cooldown-hours</string>
    <string>${COOLDOWN_HOURS}</string>
$(if [[ "${VM_MODE}" == "1" ]]; then cat <<EOF
    <string>--vm-mode</string>
    <string>--vm-host</string>
    <string>${VM_HOST}</string>
    <string>--vm-user</string>
    <string>${VM_USER}</string>
    <string>--vm-key</string>
    <string>${VM_KEY}</string>
EOF
fi)
  </array>
  <key>StartInterval</key>
  <integer>${INTERVAL_SEC}</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${ROOT}/review_out/ibkr_gateway_watch.launchagent.out.log</string>
  <key>StandardErrorPath</key>
  <string>${ROOT}/review_out/ibkr_gateway_watch.launchagent.err.log</string>
</dict>
</plist>
PLIST

launchctl unload "$PLIST" >/dev/null 2>&1 || true
launchctl load "$PLIST"
launchctl kickstart -k "gui/$(id -u)/${LABEL}" >/dev/null 2>&1 || true

echo "installed: ${LABEL}"
echo "plist: ${PLIST}"
echo "interval: ${INTERVAL_SEC}s"
echo "timeout: ${TIMEOUT_SEC}s"
echo "cooldown: ${COOLDOWN_HOURS}h"
echo "vm_mode: ${VM_MODE}"
echo "logs: ${ROOT}/review_out/ibkr_gateway_watch.launchagent.out.log"
echo "state: ${ROOT}/review_out/ibkr_gateway_watch_state.json"
