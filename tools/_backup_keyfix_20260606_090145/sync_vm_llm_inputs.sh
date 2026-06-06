#!/usr/bin/env bash
set -euo pipefail

MAIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

VM_HOST="${VM_HOST:-161.33.26.35}"
VM_USER="${VM_USER:-ubuntu}"
VM_KEY="${VM_KEY:-/Users/tani/Downloads/ssh-key-2026-03-04-4.key}"
REMOTE_ROOT="${REMOTE_ROOT:-/home/ubuntu/trading_bot}"
REMOTE_MAIN_DIR="${REMOTE_MAIN_DIR:-${REMOTE_ROOT}/MAIN}"
DAY8="${1:-${DAY8:-}}"
SNAPSHOT_ROOT="${SNAPSHOT_ROOT:-${MAIN_DIR}/.local_llm/vm_snapshot}"
SNAPSHOT_NAME="${SNAPSHOT_NAME:-$(date '+%Y%m%d_%H%M%S')}"
OUT_DIR="${SNAPSHOT_ROOT}/${SNAPSHOT_NAME}"

SSH_OPTS=(-o IdentitiesOnly=yes -o ConnectTimeout=10 -i "${VM_KEY}")
REMOTE="${VM_USER}@${VM_HOST}"

copy_remote() {
  local remote_glob="$1"
  local dest_dir="$2"
  mkdir -p "${dest_dir}"
  scp "${SSH_OPTS[@]}" -q "${REMOTE}:${remote_glob}" "${dest_dir}/" >/dev/null 2>&1 || true
}

validate_snapshot() {
  local main_log_count shadow_log_count
  main_log_count="$(find "${OUT_DIR}/logs" -maxdepth 1 -type f -name 'trade_log_*.csv' | wc -l | tr -d ' ')"
  shadow_log_count="$(find "${OUT_DIR}/logs/instances/shadow" -maxdepth 1 -type f -name 'trade_log_*.csv' | wc -l | tr -d ' ')"

  if [[ ! -f "${OUT_DIR}/MAIN/CONTROL.csv" ]]; then
    echo "[ERROR] snapshot missing MAIN/CONTROL.csv" >&2
    echo "[ERROR] Check VM_HOST/REMOTE_ROOT/network permission. Snapshot was not usable." >&2
    exit 2
  fi
  if [[ "${main_log_count}" -eq 0 ]]; then
    echo "[ERROR] snapshot missing main trade logs" >&2
    echo "[ERROR] Check REMOTE_ROOT/logs or network permission. Snapshot was not usable." >&2
    exit 2
  fi

  echo "[INFO] copied main_logs=${main_log_count} shadow_logs=${shadow_log_count}"
  if [[ ! -f "${OUT_DIR}/MAIN/ai_model.json" ]]; then
    echo "[WARN] snapshot missing MAIN/ai_model.json; review will use defaults"
  fi
}

main() {
  echo "[INFO] local-only VM snapshot sync"
  echo "[INFO] remote=${REMOTE}"
  echo "[INFO] out=${OUT_DIR}"
  echo "[INFO] mode=read-only; VM files/services are not modified"

  mkdir -p "${OUT_DIR}/MAIN/daily_report_out" \
    "${OUT_DIR}/logs/instances/shadow" \
    "${OUT_DIR}/logs/instances/mr_observe"

  copy_remote "${REMOTE_MAIN_DIR}/CONTROL.csv" "${OUT_DIR}/MAIN"
  copy_remote "${REMOTE_MAIN_DIR}/ai_model.json" "${OUT_DIR}/MAIN"
  copy_remote "${REMOTE_MAIN_DIR}/state.json" "${OUT_DIR}/MAIN"

  if [[ -n "${DAY8}" ]]; then
    copy_remote "${REMOTE_ROOT}/logs/trade_log_${DAY8}.csv" "${OUT_DIR}/logs"
    copy_remote "${REMOTE_ROOT}/logs/instances/shadow/trade_log_${DAY8}.csv" "${OUT_DIR}/logs/instances/shadow"
    copy_remote "${REMOTE_ROOT}/logs/instances/mr_observe/trade_log_${DAY8}.csv" "${OUT_DIR}/logs/instances/mr_observe"
    copy_remote "${REMOTE_MAIN_DIR}/daily_report_out/daily_reflection_${DAY8}.json" "${OUT_DIR}/MAIN/daily_report_out"
  else
    copy_remote "${REMOTE_ROOT}/logs/trade_log_*.csv" "${OUT_DIR}/logs"
    copy_remote "${REMOTE_ROOT}/logs/instances/shadow/trade_log_*.csv" "${OUT_DIR}/logs/instances/shadow"
    copy_remote "${REMOTE_ROOT}/logs/instances/mr_observe/trade_log_*.csv" "${OUT_DIR}/logs/instances/mr_observe"
    copy_remote "${REMOTE_MAIN_DIR}/daily_report_out/daily_reflection_*.json" "${OUT_DIR}/MAIN/daily_report_out"
  fi

  validate_snapshot

  ln -sfn "${OUT_DIR}" "${SNAPSHOT_ROOT}/latest"

  echo "[OK] snapshot=${OUT_DIR}"
  echo "[OK] latest=${SNAPSHOT_ROOT}/latest"
  echo ""
  echo "Next:"
  echo "  cd ${MAIN_DIR}"
  echo "  python3 tools/local_llm_trade_review.py --snapshot-dir '${SNAPSHOT_ROOT}/latest'"
}

main "$@"
