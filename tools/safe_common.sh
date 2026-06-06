#!/usr/bin/env bash
set -euo pipefail

safe_main_dir() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cd "${script_dir}/.." && pwd
}

safe_control_export() {
  local control_csv="$1"
  local py_bin="${PY_BIN:-python3}"
  "${py_bin}" - "$control_csv" <<'PY'
import csv
import sys
from pathlib import Path

path = Path(sys.argv[1]).resolve()
rows = {}
if path.exists():
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.reader(f):
            if len(r) < 2:
                continue
            k = str(r[0]).strip()
            v = str(r[1]).strip()
            if not k or k.lower() == "key":
                continue
            rows[k] = v

def bval(v: str, default: bool) -> bool:
    s = str(v if v is not None else "").strip().lower()
    if not s:
        return default
    return s in ("1", "true", "yes", "on")

def fval(v: str, default: float) -> float:
    try:
        return float(str(v).strip())
    except Exception:
        return default

paper_mode = bval(rows.get("paper_mode"), True)
live_enabled = bval(rows.get("live_enabled"), False)
today_on = bval(rows.get("today_on"), True)
trade_enabled = bval(rows.get("trade_enabled"), True)
observe_only = bval(rows.get("observe_only"), False)
safety_hard_block = bval(rows.get("safety_hard_block"), False)
daily_loss_limit_pct = fval(rows.get("daily_loss_limit_pct"), -1.0)

live_candidate = (
    (not paper_mode)
    and live_enabled
    and today_on
    and trade_enabled
    and (not observe_only)
    and (not safety_hard_block)
)

print(f"PAPER_MODE={'1' if paper_mode else '0'}")
print(f"LIVE_ENABLED={'1' if live_enabled else '0'}")
print(f"TODAY_ON={'1' if today_on else '0'}")
print(f"TRADE_ENABLED={'1' if trade_enabled else '0'}")
print(f"OBSERVE_ONLY={'1' if observe_only else '0'}")
print(f"SAFETY_HARD_BLOCK={'1' if safety_hard_block else '0'}")
print(f"DAILY_LOSS_LIMIT_PCT={daily_loss_limit_pct:.6f}")
print(f"DAILY_LOSS_VALID={'1' if daily_loss_limit_pct < 0 else '0'}")
print(f"LIVE_CANDIDATE={'1' if live_candidate else '0'}")
PY
}

safe_lock_pid() {
  local lock_dir="$1"
  local lock_file="${lock_dir}/lockinfo.txt"
  if [[ ! -f "${lock_file}" ]]; then
    return 0
  fi
  awk -F= '/^pid=/{print $2; exit}' "${lock_file}" | tr -d '[:space:]'
}

safe_pid_alive() {
  local pid="${1:-}"
  if [[ -z "${pid}" ]]; then
    return 1
  fi
  kill -0 "${pid}" 2>/dev/null
}

safe_clear_stale_lock() {
  local lock_dir="$1"
  if [[ ! -d "${lock_dir}" ]]; then
    return 0
  fi

  local pid=""
  pid="$(safe_lock_pid "${lock_dir}")"
  if safe_pid_alive "${pid}"; then
    echo "[INFO] lock active: ${lock_dir} pid=${pid}"
    return 0
  fi

  rm -rf "${lock_dir}"
  echo "[WARN] cleared stale lock: ${lock_dir} (pid=${pid:-none})"
}
