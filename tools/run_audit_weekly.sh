#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MAIN_DIR="${SCRIPT_DIR}/.."
VENV="${MAIN_DIR}/.venv/bin/python"

# Compute previous week Mon-Sun using Python (portable: works on Linux and macOS)
read -r START END < <("$VENV" - <<'PYEOF'
from datetime import date, timedelta
today = date.today()
# Most recent past Sunday (isoweekday: Mon=1 ... Sun=7)
days_since_sun = today.isoweekday() % 7  # 0 if today is Sun
last_sun = today - timedelta(days=days_since_sun if days_since_sun > 0 else 7)
last_mon = last_sun - timedelta(days=6)
print(last_mon.strftime("%Y%m%d"), last_sun.strftime("%Y%m%d"))
PYEOF
)

echo "[audit-weekly] range: ${START} - ${END}"
"$VENV" "${MAIN_DIR}/audit.py" --start "${START}" --end "${END}"
# Keep only 20 most recent weekly audit files
ls -1t "${MAIN_DIR}/audit_out"/audit_*_*.json 2>/dev/null | tail -n +21 | xargs rm -f 2>/dev/null || true
echo "[audit-weekly] done"
