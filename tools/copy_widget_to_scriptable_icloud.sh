#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
MAIN_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
SRC="${1:-$MAIN_DIR/widget/scriptable/export/OuroborosWidget.local.transfer.js}"
DEST_NAME="${2:-OuroborosWidget.local.js}"
ICLOUD_SCRIPTABLE_DIR="${HOME}/Library/Mobile Documents/iCloud~dk~simonbs~Scriptable/Documents"

if [[ ! -f "$SRC" ]]; then
  echo "source not found: $SRC" >&2
  echo "Run ./tools/export_scriptable_widget.sh first." >&2
  exit 1
fi

if [[ ! -d "$ICLOUD_SCRIPTABLE_DIR" ]]; then
  echo "Scriptable iCloud folder not found: $ICLOUD_SCRIPTABLE_DIR" >&2
  echo "Enable iCloud Drive in Scriptable on iPhone/iPad first." >&2
  exit 1
fi

DEST_PATH="${ICLOUD_SCRIPTABLE_DIR}/${DEST_NAME}"
cp "$SRC" "$DEST_PATH"

echo "Copied:"
echo "  $SRC"
echo "-> $DEST_PATH"
echo ""
echo "Next:"
echo "  1. Open Scriptable on iPhone"
echo "  2. Wait for iCloud sync"
echo "  3. The script should appear as ${DEST_NAME:r}"
