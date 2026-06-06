#!/usr/bin/env bash
set -euo pipefail

SERVICE="${1:-ouroboros.bitflyer}"
ACCOUNT_KEY="${2:-api_key}"
ACCOUNT_SECRET="${3:-api_secret}"

cat <<EOF
[INFO] Register bitFlyer API credentials into macOS Keychain
  service:         ${SERVICE}
  account(apiKey): ${ACCOUNT_KEY}
  account(secret): ${ACCOUNT_SECRET}

This script never puts secrets in command arguments.
You will be prompted securely by macOS 'security' command.
EOF

read -r -p "Continue? [y/N]: " ans
case "${ans}" in
  y|Y|yes|YES) ;;
  *) echo "[ABORT]"; exit 1 ;;
esac

echo
echo "[STEP] Enter API KEY value when prompted."
# -T "" removes default trusted-app access so each access requires confirmation.
security add-generic-password -a "${ACCOUNT_KEY}" -s "${SERVICE}" -U -T "" -w

echo
echo "[STEP] Enter API SECRET value when prompted."
security add-generic-password -a "${ACCOUNT_SECRET}" -s "${SERVICE}" -U -T "" -w

echo
echo "[OK] Saved to Keychain."
echo "[NEXT] Run: python3 tools/live_preflight.py"
echo "[NOTE] Do NOT click 'Always Allow' on Keychain access prompts if you prioritize secrecy."
