#!/usr/bin/env bash
set -euo pipefail

LABEL="com.ouroboros.unified.dashboard.healthcheck"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"

launchctl unload "$PLIST" >/dev/null 2>&1 || true
rm -f "$PLIST"

echo "uninstalled: ${LABEL}"
