#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
MAIN_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
SRC="${1:-$MAIN_DIR/widget/scriptable/OuroborosWidget.local.js}"
DEST_NAME="${2:-OuroborosWidget.local.js}"
SRC_BASE=$(basename "$SRC")
SRC_BASE_NO_EXT="${SRC_BASE%.*}"

cd "$MAIN_DIR"
"$SCRIPT_DIR/export_scriptable_widget.sh" "$SRC"
"$SCRIPT_DIR/copy_widget_to_scriptable_icloud.sh" "$MAIN_DIR/widget/scriptable/export/${SRC_BASE_NO_EXT}.transfer.js" "$DEST_NAME"

echo ""
echo "Published to Scriptable iCloud:"
echo "  $DEST_NAME"
