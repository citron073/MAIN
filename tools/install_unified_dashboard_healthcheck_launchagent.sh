#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.ouroboros.unified.dashboard.healthcheck"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3)}"
HOUR="${HOUR:-8}"
MINUTE="${MINUTE:-5}"
TIMEOUT_SEC="${TIMEOUT_SEC:-15}"

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
    <string>${ROOT}/tools/daily_ops_check.py</string>
    <string>--timeout-sec</string>
    <string>${TIMEOUT_SEC}</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>${HOUR}</integer>
    <key>Minute</key>
    <integer>${MINUTE}</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${ROOT}/review_out/unified_dashboard_healthcheck.launchagent.out.log</string>
  <key>StandardErrorPath</key>
  <string>${ROOT}/review_out/unified_dashboard_healthcheck.launchagent.err.log</string>
</dict>
</plist>
PLIST

launchctl unload "$PLIST" >/dev/null 2>&1 || true
launchctl load "$PLIST"
launchctl kickstart -k "gui/$(id -u)/${LABEL}" >/dev/null 2>&1 || true

echo "installed: ${LABEL}"
echo "plist: ${PLIST}"
echo "schedule: every day ${HOUR}:$(printf '%02d' "$MINUTE")"
echo "timeout: ${TIMEOUT_SEC}s"
echo "daily json: ${ROOT}/review_out/daily_ops_check_YYYYMMDD.json"
echo "dashboard json: ${ROOT}/review_out/unified_dashboard_health_YYYYMMDD.json"
echo "zero-day json: ${ROOT}/review_out/trade_log_zero_day_review_YYYYMMDD.json"
echo "history: ${ROOT}/review_out/unified_dashboard_health_history.jsonl"
