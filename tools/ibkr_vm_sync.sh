#!/usr/bin/env bash
# ibkr_vm_sync.sh — SSH-sync IBKR trade logs and state from VM to Mac
# Runs inside US market hours (JST 22:00-07:00); safe to call outside hours too.
# Writes: .local_llm/ibkr/logs/ibkr_trade_log_*.csv
#         .local_llm/ibkr/ibkr_state.json
#         review_out/ibkr_vm_sync_status.json

set -euo pipefail

MAIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VM_HOST="${VM_HOST:-161.33.26.35}"
VM_USER="${VM_USER:-ubuntu}"
VM_KEY="${VM_KEY:-/Users/tani/.ssh/ouroboros_vm_key}"
REMOTE_ROOT="${REMOTE_ROOT:-/home/ubuntu/trading_bot}"
OUT_DIR="${MAIN_DIR}/.local_llm/ibkr"
LOG_DIR="${OUT_DIR}/logs"
STATUS_JSON="${MAIN_DIR}/review_out/ibkr_vm_sync_status.json"
FORCE="${1:-}"

# US market hours gate (JST 22:00-07:00) — skip with FORCE=1 or --force
if [[ "${FORCE}" != "--force" && "${FORCE}" != "1" ]]; then
    HOUR=$(TZ=Asia/Tokyo date +%-H 2>/dev/null || TZ=Asia/Tokyo date +%H | sed 's/^0//')
    HOUR="${HOUR:-0}"
    if ! ([[ "$HOUR" -ge 22 ]] || [[ "$HOUR" -lt 7 ]]); then
        echo "[ibkr_vm_sync] outside US hours (JST ${HOUR}h), skip. Use --force to override."
        exit 0
    fi
fi

mkdir -p "${LOG_DIR}" "${MAIN_DIR}/review_out"

SSH_OPTS=(-o IdentitiesOnly=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=no -o BatchMode=yes -i "${VM_KEY}")

# Fetch files from VM (failures tolerated — bot may not have traded yet)
scp "${SSH_OPTS[@]}" "${VM_USER}@${VM_HOST}:${REMOTE_ROOT}/MAIN/ibkr_state.json"      "${OUT_DIR}/" 2>/dev/null || true
scp "${SSH_OPTS[@]}" "${VM_USER}@${VM_HOST}:${REMOTE_ROOT}/MAIN/IBKR_CONTROL.csv"    "${OUT_DIR}/" 2>/dev/null || true
scp "${SSH_OPTS[@]}" "${VM_USER}@${VM_HOST}:${REMOTE_ROOT}/logs/ibkr_trade_log_*.csv" "${LOG_DIR}/" 2>/dev/null || true

# Check VM bot service status via SSH
BOT_STATUS=$(ssh "${SSH_OPTS[@]}" "${VM_USER}@${VM_HOST}" \
    "systemctl is-active ouroboros-ibkr-bot.service 2>/dev/null || echo unknown" 2>/dev/null || echo "ssh_error")

UPDATED_AT=$(date -u +"%Y-%m-%d %H:%M:%S")

/usr/bin/python3 - <<PYEOF
import json, glob, os
from pathlib import Path

log_files = sorted(os.path.basename(f) for f in glob.glob("${LOG_DIR}/ibkr_trade_log_*.csv"))
state: dict = {}
try:
    state = json.loads(Path("${OUT_DIR}/ibkr_state.json").read_text())
except Exception:
    pass

out = {
    "updated_at": "${UPDATED_AT}",
    "bot_service": "${BOT_STATUS}",
    "log_files": log_files,
    "state": state,
}
Path("${STATUS_JSON}").write_text(json.dumps(out, ensure_ascii=False, indent=2))
print(f"[ibkr_vm_sync] OK bot_service=${BOT_STATUS} logs={len(log_files)}")
PYEOF
