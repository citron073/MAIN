#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MAIN_DIR="${SCRIPT_DIR}/.."
VENV_PY="${MAIN_DIR}/.venv/bin/python"
TODAY="$(date +%Y%m%d)"
BACKUP_DIR="${MAIN_DIR}/state_backups"
mkdir -p "$BACKUP_DIR"

corrupt_files=()

for state_file in state.json state_shadow.json state_mr_observe.json; do
    src="${MAIN_DIR}/${state_file}"
    if [ ! -f "$src" ]; then
        continue
    fi
    # Validate JSON before backup — pass path as argv to avoid quoting issues
    if ! "$VENV_PY" -c 'import json,sys; json.load(open(sys.argv[1]))' "$src" 2>/dev/null; then
        echo "[state-backup] SKIP ${state_file}: invalid JSON (not backed up)"
        corrupt_files+=("${state_file}")
        continue
    fi
    cp "$src" "${BACKUP_DIR}/${state_file}.bak_${TODAY}"
    echo "[state-backup] ${state_file} -> ${BACKUP_DIR}/${state_file}.bak_${TODAY}"
done

# Keep only 30 most recent backups per state file
for pattern in state.json state_shadow.json state_mr_observe.json; do
    ls -1t "${BACKUP_DIR}/${pattern}.bak_"* 2>/dev/null | tail -n +31 | xargs rm -f 2>/dev/null || true
done

# Write state_backup status to .ops_checks.json (dashboard Q4 panel picks this up)
OPS_PATH="${MAIN_DIR}/.ops_checks.json"
CORRUPT_COUNT="${#corrupt_files[@]}"
CORRUPT_NAMES="${corrupt_files[*]:-}"
"$VENV_PY" -c '
import json, time, pathlib, sys
ops = pathlib.Path(sys.argv[1])
corrupt_n = int(sys.argv[2])
corrupt_names = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else ""
try:
    d = {}
    if ops.exists():
        try: d = json.loads(ops.read_text())
        except: pass
    now = time.time()
    ns = time.strftime("%Y-%m-%d %H:%M:%S")
    d["state_backup"] = {
        "ok": corrupt_n == 0, "rc": 1 if corrupt_n else 0,
        "updated_at": ns, "updated_ts": now,
        "output": f"done, corrupt={corrupt_n}"
    }
    if corrupt_n > 0:
        d["state_backup_corrupt"] = {
            "ok": False, "rc": 1,
            "updated_at": ns, "updated_ts": now,
            "file": corrupt_names
        }
    tmp = ops.with_suffix(ops.suffix + ".tmp")
    tmp.write_text(json.dumps(d, indent=2) + "\n")
    tmp.replace(ops)
except Exception as e:
    print(f"[state-backup] warn: {e}", file=sys.stderr)
' "$OPS_PATH" "$CORRUPT_COUNT" "$CORRUPT_NAMES" 2>/dev/null || true

echo "[state-backup] done: ${TODAY}"
