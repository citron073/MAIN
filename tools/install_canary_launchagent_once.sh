#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAIN_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
WRAPPER="${MAIN_DIR}/tools/canary_live_once_wrapper.sh"

TARGET_DATE="$(date -v+1d '+%Y-%m-%d')"
HOUR=10
MINUTE=5
DURATION_SEC=600
INTERVAL_SEC=60
LOT=""
LABEL="com.ouroboros.canary.once"
LAUNCH_DIR="${HOME}/Library/LaunchAgents"

usage() {
  cat <<'USAGE'
Usage:
  ./tools/install_canary_launchagent_once.sh [options]

Options:
  --date YYYY-MM-DD     Target date (default: tomorrow)
  --hour N              Trigger hour (default: 10)
  --minute N            Trigger minute (default: 5)
  --duration-sec N      Canary run duration (default: 600)
  --interval-sec N      run.py interval (default: 60)
  --lot BTC             Optional canary lot override (example: 0.001)
  --label NAME          LaunchAgent label (default: com.ouroboros.canary.once)
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --date)
      TARGET_DATE="$2"
      shift 2
      ;;
    --hour)
      HOUR="$2"
      shift 2
      ;;
    --minute)
      MINUTE="$2"
      shift 2
      ;;
    --duration-sec)
      DURATION_SEC="$2"
      shift 2
      ;;
    --interval-sec)
      INTERVAL_SEC="$2"
      shift 2
      ;;
    --lot)
      LOT="$2"
      shift 2
      ;;
    --label)
      LABEL="$2"
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

python3 - <<'PY' "${TARGET_DATE}" "${HOUR}" "${MINUTE}" "${DURATION_SEC}" "${INTERVAL_SEC}"
import re
import sys

date_s, hour_s, minute_s, dur_s, int_s = sys.argv[1:6]
if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_s):
    raise SystemExit("[FAIL] --date must be YYYY-MM-DD")
hour = int(hour_s)
minute = int(minute_s)
dur = int(dur_s)
interval = int(int_s)
if not (0 <= hour <= 23):
    raise SystemExit("[FAIL] --hour must be 0..23")
if not (0 <= minute <= 59):
    raise SystemExit("[FAIL] --minute must be 0..59")
if dur < 60:
    raise SystemExit("[FAIL] --duration-sec must be >= 60")
if interval < 30:
    raise SystemExit("[FAIL] --interval-sec must be >= 30")
PY

if [[ ! -x "${WRAPPER}" ]]; then
  echo "[FAIL] wrapper not executable: ${WRAPPER}" >&2
  exit 2
fi

MONTH="${TARGET_DATE:5:2}"
DAY="${TARGET_DATE:8:2}"
MONTH_INT=$((10#${MONTH}))
DAY_INT=$((10#${DAY}))
PLIST_PATH="${LAUNCH_DIR}/${LABEL}.plist"

mkdir -p "${LAUNCH_DIR}" "${MAIN_DIR}/ci_logs"

UID_NUM="$(id -u)"
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
      <string>${WRAPPER}</string>
      <string>--target-date</string>
      <string>${TARGET_DATE}</string>
      <string>--duration-sec</string>
      <string>${DURATION_SEC}</string>
      <string>--interval-sec</string>
      <string>${INTERVAL_SEC}</string>
      <string>--label</string>
      <string>${LABEL}</string>
      <string>--plist-path</string>
      <string>${PLIST_PATH}</string>
PLIST

if [[ -n "${LOT}" ]]; then
  cat >> "${PLIST_PATH}" <<PLIST
      <string>--lot</string>
      <string>${LOT}</string>
PLIST
fi

cat >> "${PLIST_PATH}" <<PLIST
    </array>

    <key>StartCalendarInterval</key>
    <dict>
      <key>Month</key><integer>${MONTH_INT}</integer>
      <key>Day</key><integer>${DAY_INT}</integer>
      <key>Hour</key><integer>${HOUR}</integer>
      <key>Minute</key><integer>${MINUTE}</integer>
    </dict>

    <key>RunAtLoad</key>
    <false/>

    <key>StandardOutPath</key>
    <string>${MAIN_DIR}/ci_logs/launchd_canary_once_out.log</string>
    <key>StandardErrorPath</key>
    <string>${MAIN_DIR}/ci_logs/launchd_canary_once_err.log</string>
  </dict>
</plist>
PLIST

chmod 644 "${PLIST_PATH}"

launchctl bootstrap "gui/${UID_NUM}" "${PLIST_PATH}" >/dev/null 2>&1 || launchctl load "${PLIST_PATH}"

echo "[OK] launch agent installed"
echo "[INFO] label=${LABEL}"
echo "[INFO] plist=${PLIST_PATH}"
echo "[INFO] schedule=${TARGET_DATE} ${HOUR}:$(printf '%02d' "${MINUTE}")"
echo "[INFO] wrapper=${WRAPPER}"
echo "[INFO] to inspect: launchctl print gui/${UID_NUM}/${LABEL}"
echo "[INFO] to remove: ${MAIN_DIR}/tools/uninstall_canary_launchagent_once.sh --label ${LABEL}"
