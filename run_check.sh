#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DAY8="${1:-$(date +%Y%m%d)}"
cd "$SCRIPT_DIR"

if python3 ./ci_check.py "$DAY8"; then
    CI_RC=0
else
    CI_RC=$?
fi

python3 ./tools/write_ops_check.py 'run_check.sh' "$CI_RC" "ci_check rc=$CI_RC day8=$DAY8" "bash $SCRIPT_DIR/run_check.sh $DAY8" || true
exit $CI_RC
