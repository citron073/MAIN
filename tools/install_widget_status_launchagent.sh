#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAIN_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LAUNCHER="${MAIN_DIR}/tools/start_widget_status_server.sh"

LABEL="com.ouroboros.widget.status"
HOST="0.0.0.0"
PORT="8787"
TOKEN="${WIDGET_STATUS_TOKEN:-}"
REPLACE_RUNNING=0
LAUNCH_DIR="${HOME}/Library/LaunchAgents"

usage() {
  cat <<'USAGE'
Usage:
  ./tools/install_widget_status_launchagent.sh [options]

Options:
  --label NAME              LaunchAgent label (default: com.ouroboros.widget.status)
  --host HOST               Bind host (default: 0.0.0.0)
  --port PORT               Bind port (default: 8787)
  --token TOKEN             Access token for widget server
  --replace-running         Stop existing widget_status listener on the same port before install
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --label)
      LABEL="$2"
      shift 2
      ;;
    --host)
      HOST="$2"
      shift 2
      ;;
    --port)
      PORT="$2"
      shift 2
      ;;
    --token)
      TOKEN="$2"
      shift 2
      ;;
    --replace-running)
      REPLACE_RUNNING=1
      shift
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

python3 - <<'PY' "${PORT}"
import sys
p = int(sys.argv[1])
if p < 1 or p > 65535:
    raise SystemExit("[FAIL] --port must be 1..65535")
PY

if [[ ! -x "${LAUNCHER}" ]]; then
  echo "[FAIL] launcher not executable: ${LAUNCHER}" >&2
  exit 2
fi

mkdir -p "${LAUNCH_DIR}" "${MAIN_DIR}/ci_logs"
PLIST_PATH="${LAUNCH_DIR}/${LABEL}.plist"
UID_NUM="$(id -u)"
PY_BIN="$(command -v python3 || true)"
PATH_VAL="${PATH:-/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin}"

if [[ -z "${PY_BIN}" ]]; then
  PY_BIN="/usr/bin/python3"
fi

if [[ "${REPLACE_RUNNING}" == "1" ]]; then
  pids="$(lsof -t -nP -iTCP:${PORT} -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "${pids}" ]]; then
    while read -r pid; do
      [[ -z "${pid}" ]] && continue
      cmdline="$(ps -p "${pid}" -o command= 2>/dev/null || true)"
      if [[ "${cmdline}" == *"widget_status.py"* ]]; then
        kill "${pid}" >/dev/null 2>&1 || true
        echo "[INFO] stopped existing widget_status listener pid=${pid}"
      fi
    done <<< "${pids}"
    sleep 1
  fi
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
    </array>

    <key>WorkingDirectory</key>
    <string>${MAIN_DIR}</string>

    <key>EnvironmentVariables</key>
    <dict>
      <key>PY_BIN</key><string>${PY_BIN}</string>
      <key>PATH</key><string>${PATH_VAL}</string>
      <key>WIDGET_STATUS_HOST</key><string>${HOST}</string>
      <key>WIDGET_STATUS_PORT</key><string>${PORT}</string>
      <key>WIDGET_STATUS_TOKEN</key><string>${TOKEN}</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>${MAIN_DIR}/ci_logs/launchd_widget_status_out.log</string>
    <key>StandardErrorPath</key>
    <string>${MAIN_DIR}/ci_logs/launchd_widget_status_err.log</string>
  </dict>
</plist>
PLIST

chmod 644 "${PLIST_PATH}"

launchctl bootstrap "gui/${UID_NUM}" "${PLIST_PATH}" >/dev/null 2>&1 || launchctl load "${PLIST_PATH}"
launchctl kickstart -k "gui/${UID_NUM}/${LABEL}" >/dev/null 2>&1 || true

echo "[OK] widget status launch agent installed"
echo "[INFO] label=${LABEL}"
echo "[INFO] plist=${PLIST_PATH}"
echo "[INFO] url=http://127.0.0.1:${PORT}/"
if [[ -n "${TOKEN}" ]]; then
  echo "[INFO] token url=http://127.0.0.1:${PORT}/?token=${TOKEN}"
fi
echo "[INFO] inspect: launchctl print gui/${UID_NUM}/${LABEL}"
echo "[INFO] logs: ${MAIN_DIR}/ci_logs/launchd_widget_status_out.log"
echo "[INFO] remove: ${MAIN_DIR}/tools/uninstall_widget_status_launchagent.sh --label ${LABEL}"
