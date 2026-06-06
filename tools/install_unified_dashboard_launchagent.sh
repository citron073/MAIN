#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAIN_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LAUNCHER="${MAIN_DIR}/tools/start_unified_dashboard.sh"

LABEL="com.ouroboros.unified.dashboard"
MODE="tailscale"
PORT="8793"
LAUNCH_DIR="${HOME}/Library/LaunchAgents"

usage() {
  cat <<'USAGE'
Usage:
  ./tools/install_unified_dashboard_launchagent.sh [options]

Options:
  --label NAME      LaunchAgent label (default: com.ouroboros.unified.dashboard)
  --mode MODE       tailscale or public (default: tailscale)
  --port PORT       Bind port (default: 8793)
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --label)
      LABEL="$2"
      shift 2
      ;;
    --mode)
      MODE="$2"
      shift 2
      ;;
    --port)
      PORT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[FAIL] unknown arg: $1" >&2
      usage
      exit 1
      ;;
  esac
done

python3 - "${PORT}" "${MODE}" <<'PY'
import sys

port = int(sys.argv[1])
mode = sys.argv[2]
if port < 1 or port > 65535:
    raise SystemExit("[FAIL] --port must be 1..65535")
if mode not in {"tailscale", "public"}:
    raise SystemExit("[FAIL] --mode must be tailscale or public")
PY

if [[ ! -x "${LAUNCHER}" ]]; then
  echo "[FAIL] launcher not executable: ${LAUNCHER}" >&2
  exit 2
fi

mkdir -p "${LAUNCH_DIR}" "${MAIN_DIR}/ci_logs"
PLIST_PATH="${LAUNCH_DIR}/${LABEL}.plist"
UID_NUM="$(id -u)"
PATH_VAL="${PATH:-/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin}"
MODE_ARG="--tailscale"
if [[ "${MODE}" == "public" ]]; then
  MODE_ARG="--public"
fi

if [[ -f "${PLIST_PATH}" ]]; then
  launchctl bootout "gui/${UID_NUM}" "${PLIST_PATH}" >/dev/null 2>&1 || launchctl unload "${PLIST_PATH}" >/dev/null 2>&1 || true
  rm -f "${PLIST_PATH}"
fi

cat > "${PLIST_PATH}" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>${LABEL}</string>

    <key>ProgramArguments</key>
    <array>
      <string>${LAUNCHER}</string>
      <string>${MODE_ARG}</string>
      <string>--port</string>
      <string>${PORT}</string>
    </array>

    <key>WorkingDirectory</key>
    <string>${MAIN_DIR}</string>

    <key>EnvironmentVariables</key>
    <dict>
      <key>PATH</key><string>${PATH_VAL}</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>${MAIN_DIR}/ci_logs/launchd_unified_dashboard_out.log</string>
    <key>StandardErrorPath</key>
    <string>${MAIN_DIR}/ci_logs/launchd_unified_dashboard_err.log</string>
  </dict>
</plist>
PLIST

chmod 644 "${PLIST_PATH}"

launchctl bootstrap "gui/${UID_NUM}" "${PLIST_PATH}" >/dev/null 2>&1 || launchctl load "${PLIST_PATH}"
launchctl kickstart -k "gui/${UID_NUM}/${LABEL}" >/dev/null 2>&1 || true

echo "[OK] unified dashboard launch agent installed"
echo "[INFO] label=${LABEL}"
echo "[INFO] mode=${MODE}"
echo "[INFO] port=${PORT}"
echo "[INFO] plist=${PLIST_PATH}"
echo "[INFO] logs: ${MAIN_DIR}/ci_logs/launchd_unified_dashboard_out.log"
echo "[INFO] inspect: launchctl print gui/${UID_NUM}/${LABEL}"
echo "[INFO] remove: ${MAIN_DIR}/tools/uninstall_unified_dashboard_launchagent.sh --label ${LABEL}"
