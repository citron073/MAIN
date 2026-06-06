#!/usr/bin/env bash
set -euo pipefail

MAIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONTROL_MAIN="${MAIN_DIR}/CONTROL.csv"
CONTROL_SHADOW="${MAIN_DIR}/CONTROL_shadow.csv"
LOCK_DIR="${MAIN_DIR}/.run_lock_shadow"
LOG_FILE="${MAIN_DIR}/run_shadow.log"
INTERVAL="${1:-300}"

if [[ ! "${INTERVAL}" =~ ^[0-9]+$ ]]; then
  echo "[ERROR] interval must be integer seconds (example: 300)" >&2
  exit 2
fi

python3 - "$CONTROL_MAIN" "$CONTROL_SHADOW" <<'PY'
import csv
import sys
from pathlib import Path

src = Path(sys.argv[1])
dst = Path(sys.argv[2])

rows = {}
if src.exists():
    with src.open(newline="", encoding="utf-8") as f:
        for r in csv.reader(f):
            if len(r) < 2:
                continue
            k = str(r[0]).strip()
            v = str(r[1]).strip()
            if not k or k.lower() == "key":
                continue
            rows[k] = v

# Safe shadow defaults: paper-only, 24h verification.
rows["today_on"] = "1"
rows["trade_enabled"] = "1"
rows["paper_mode"] = "1"
rows["live_enabled"] = "0"
rows["observe_only"] = "0"
rows["safety_hard_block"] = "0"
rows["rollout_mode"] = "AUTO"
rows["start_hour"] = "0"
rows["end_hour"] = "24"
rows["no_paper_hours"] = ""
rows["exchange_name"] = "bitflyer"

dst.parent.mkdir(parents=True, exist_ok=True)
with dst.open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["key", "value"])
    for k in sorted(rows.keys()):
        w.writerow([k, rows[k]])
print(dst)
PY

if [[ -f "${LOCK_DIR}/lockinfo.txt" ]]; then
  PID="$(awk -F= '/^pid=/{print $2}' "${LOCK_DIR}/lockinfo.txt" | tr -d '[:space:]' || true)"
  if [[ -n "${PID}" ]] && kill -0 "${PID}" 2>/dev/null; then
    echo "[INFO] shadow runner already running (pid=${PID})"
    exit 0
  fi
fi

echo "[INFO] starting shadow paper runner"
echo "[INFO] control: ${CONTROL_SHADOW}"
echo "[INFO] logs: ${MAIN_DIR}/../logs/instances/shadow"
echo "[INFO] run log: ${LOG_FILE}"

(
  export OUROBOROS_INSTANCE="shadow"
  export OUROBOROS_CONTROL_PATH="${CONTROL_SHADOW}"
  export OUROBOROS_RUN_LOCK_PATH="${LOCK_DIR}"
  nohup python3 "${MAIN_DIR}/run.py" --interval "${INTERVAL}" --print-tick >> "${LOG_FILE}" 2>&1 &
  echo "[OK] shadow started pid=$!"
)
