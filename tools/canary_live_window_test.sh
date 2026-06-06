#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAIN_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONTROL_CSV="${MAIN_DIR}/CONTROL.csv"
PREFLIGHT_PY="${MAIN_DIR}/tools/live_preflight.py"
RUN_PY="${MAIN_DIR}/run.py"
RUN_LOG="${MAIN_DIR}/run.log"
RUN_LOCK_DIR="${MAIN_DIR}/.run_lock"
LOGS_DIR="${MAIN_DIR}/../logs"

DURATION_SEC=600
INTERVAL_SEC=60
CANARY_LOT=""
FORCE_OUTSIDE_HOURS=0

usage() {
  cat <<'USAGE'
Usage:
  ./tools/canary_live_window_test.sh [--duration-sec N] [--interval-sec N] [--lot BTC] [--force-outside-hours]

Purpose:
  - Run short LIVE canary bot test in one shot.
  - Temporarily switches CONTROL to CANARY live mode, runs run.py, then restores CONTROL.

Options:
  --duration-sec N        Total run duration (default: 600)
  --interval-sec N        run.py interval seconds (default: 60)
  --lot BTC               Override canary_lot (example: 0.001)
  --force-outside-hours   Allow run outside bot trade window (10:00-15:59). Default: abort.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --duration-sec)
      DURATION_SEC="$2"
      shift 2
      ;;
    --interval-sec)
      INTERVAL_SEC="$2"
      shift 2
      ;;
    --lot)
      CANARY_LOT="$2"
      shift 2
      ;;
    --force-outside-hours)
      FORCE_OUTSIDE_HOURS=1
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

if [[ ! -f "${CONTROL_CSV}" ]]; then
  echo "[FAIL] CONTROL.csv not found: ${CONTROL_CSV}" >&2
  exit 1
fi
if [[ ! -f "${RUN_PY}" ]]; then
  echo "[FAIL] run.py not found: ${RUN_PY}" >&2
  exit 1
fi

if [[ -d "${RUN_LOCK_DIR}" ]]; then
  echo "[FAIL] .run_lock exists. Stop current bot process first." >&2
  exit 2
fi

NOW_HOUR="$(date +%H)"
if [[ "${FORCE_OUTSIDE_HOURS}" -ne 1 ]]; then
  if (( 10#${NOW_HOUR} < 10 || 10#${NOW_HOUR} >= 16 )); then
    echo "[ABORT] outside trade window now ($(date '+%Y-%m-%d %H:%M:%S'))."
    echo "[HINT] run this between 10:00 and 15:59, or pass --force-outside-hours."
    exit 3
  fi
fi

BACKUP_CSV="${MAIN_DIR}/CONTROL.csv.bak_canary_window_$(date +%Y%m%dT%H%M%S)"
cp "${CONTROL_CSV}" "${BACKUP_CSV}"
echo "[BACKUP] ${BACKUP_CSV}"

RUN_PID=""
cleanup() {
  if [[ -n "${RUN_PID}" ]]; then
    if kill -0 "${RUN_PID}" 2>/dev/null; then
      kill -INT "${RUN_PID}" 2>/dev/null || true
      sleep 2
      if kill -0 "${RUN_PID}" 2>/dev/null; then
        kill -TERM "${RUN_PID}" 2>/dev/null || true
        sleep 2
      fi
      if kill -0 "${RUN_PID}" 2>/dev/null; then
        kill -KILL "${RUN_PID}" 2>/dev/null || true
      fi
    fi
  fi
  if [[ -f "${BACKUP_CSV}" ]]; then
    cp "${BACKUP_CSV}" "${CONTROL_CSV}"
    echo "[RESTORE] CONTROL restored from ${BACKUP_CSV}"
  fi
}
trap cleanup EXIT

python3 - <<'PY' "${CONTROL_CSV}" "${CANARY_LOT}"
import csv
import sys
from pathlib import Path

p = Path(sys.argv[1])
lot = str(sys.argv[2]).strip()
updates = {
    "paper_mode": "0",
    "live_enabled": "1",
    "rollout_mode": "CANARY",
    "trade_enabled": "1",
    "today_on": "1",
    "safety_hard_block": "0",
    "fx_leverage": "1.0",
}
if lot:
    updates["canary_lot"] = lot

rows = []
with p.open(newline="", encoding="utf-8") as f:
    for row in csv.reader(f):
        if len(row) >= 2:
            k = (row[0] or "").strip()
            if k in updates:
                row[1] = updates[k]
        rows.append(row)
with p.open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerows(rows)
print("[OK] CONTROL switched to CANARY live test mode")
PY

echo "[CHECK] live preflight..."
python3 "${PREFLIGHT_PY}"

START_TS="$(date '+%Y-%m-%d %H:%M:%S')"
echo "[START] ${START_TS}"
echo "[RUN] python3 run.py --interval ${INTERVAL_SEC} --print-tick (duration=${DURATION_SEC}s)"
(
  cd "${MAIN_DIR}"
  nohup python3 "${RUN_PY}" --interval "${INTERVAL_SEC}" --print-tick >> "${RUN_LOG}" 2>&1 &
  echo $! > /tmp/ouroboros_canary_window_test.pid
)
RUN_PID="$(cat /tmp/ouroboros_canary_window_test.pid)"
echo "[RUN] pid=${RUN_PID}"

sleep 2
if ! kill -0 "${RUN_PID}" 2>/dev/null; then
  echo "[FAIL] run.py exited immediately. see ${RUN_LOG}" >&2
  exit 4
fi

sleep "${DURATION_SEC}"

if kill -0 "${RUN_PID}" 2>/dev/null; then
  kill -INT "${RUN_PID}" 2>/dev/null || true
  sleep 2
fi

TODAY="$(date +%Y%m%d)"
TRADE_LOG="${LOGS_DIR}/trade_log_${TODAY}.csv"
echo "[RESULT] start_ts=${START_TS}"
echo "[RESULT] trade_log=${TRADE_LOG}"

python3 - <<'PY' "${TRADE_LOG}" "${START_TS}"
import csv
import sys
from pathlib import Path

path = Path(sys.argv[1])
start_ts = sys.argv[2]
if not path.exists():
    print("[WARN] trade log not found for today")
    raise SystemExit(0)

rows = []
with path.open(newline="", encoding="utf-8") as f:
    r = csv.DictReader(f)
    for row in r:
        ts = str(row.get("time", "")).strip()
        note = str(row.get("note", "")).strip()
        if ts >= start_ts and "exec=LIVE" in note and "stage=CANARY" in note:
            rows.append(row)

print(f"[RESULT] live_canary_rows={len(rows)}")
for row in rows[-10:]:
    print(
        "[ROW]",
        row.get("time", ""),
        row.get("result", ""),
        row.get("side", ""),
        row.get("price", ""),
        row.get("size", ""),
        row.get("note", ""),
    )
PY

echo "[DONE] canary window test completed."
