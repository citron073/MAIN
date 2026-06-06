#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
MAIN_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
SRC="${1:-$MAIN_DIR/widget/scriptable/OuroborosWidget.local.js}"
OUT_DIR="${2:-$MAIN_DIR/widget/scriptable/export}"

if [[ ! -f "$SRC" ]]; then
  echo "source not found: $SRC" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"

BASE=$(basename "$SRC")
BASE_NO_EXT="${BASE:r}"
JS_OUT="$OUT_DIR/${BASE_NO_EXT}.transfer.js"
TXT_OUT="$OUT_DIR/${BASE_NO_EXT}.transfer.txt"

# Normalize line endings so iPhone side receives stable plain text.
perl -0pe 's/\r\n/\n/g; s/\r/\n/g' "$SRC" > "$JS_OUT"
cp "$JS_OUT" "$TXT_OUT"

if command -v node >/dev/null 2>&1; then
  node --check "$JS_OUT"
fi

echo "Exported:"
echo "  $JS_OUT"
echo "  $TXT_OUT"
echo ""
echo "Recommended transfer:"
echo "  1. Best: copy to Scriptable iCloud folder with ./tools/copy_widget_to_scriptable_icloud.sh"
echo "  2. AirDrop fallback: send the .txt file to iPhone, then copy/paste into Scriptable"
echo "  3. Avoid relying on direct .js copy/paste on iPhone Files"
echo "Avoid Apple Notes for code transfer."
