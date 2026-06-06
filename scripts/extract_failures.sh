#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

LOG_PATH="${1:-.harness/last_validate.log}"
OUT_PATH="${2:-.harness/failures.txt}"
mkdir -p "$(dirname "$OUT_PATH")"

if [[ ! -f "$LOG_PATH" ]]; then
  echo "log not found: $LOG_PATH" >&2
  exit 1
fi

{
  echo "# Harness Failure Extract"
  echo "source=$LOG_PATH"
  echo "generated_at=$(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo ""
  grep -nE "FAIL:|ERROR:|FAILED|Traceback|AssertionError|SyntaxError|ModuleNotFoundError|ImportError|Exception|error:|Error:" "$LOG_PATH" || true
  echo ""
  echo "# Tail"
  tail -n 120 "$LOG_PATH"
} > "$OUT_PATH"

echo "Extracted:"
echo "  $OUT_PATH"
