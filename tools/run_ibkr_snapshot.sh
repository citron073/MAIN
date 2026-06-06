#!/bin/bash
# Auto-run IBKR VM sync during US market hours (JST 22:00 - 07:00)
# Used by com.ouroboros.ibkr_snapshot.plist (launchd, every 5 min)
# Replaced test_ibkr_connection.py (required ib_insync on Mac) with
# ibkr_vm_sync.sh which SSHes to VM and fetches ibkr_state + trade logs.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${SCRIPT_DIR}/ibkr_vm_sync.sh"
