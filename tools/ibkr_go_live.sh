#!/usr/bin/env bash
# ibkr_go_live.sh — Atomically switch IBKR bot from paper to live mode.
# Run this on VM only after:
#   1. IBKR live account is funded
#   2. IB Gateway autologin is working
#   3. You have confirmed paper trading is working correctly
#
# Usage:
#   bash tools/ibkr_go_live.sh          # switch to live
#   bash tools/ibkr_go_live.sh --revert # switch back to paper

set -euo pipefail

MAIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
IBC_CONFIG="/home/ubuntu/ibc/config.ini"
IBKR_CONTROL="$MAIN_DIR/IBKR_CONTROL.csv"

REVERT=0
if [[ "${1:-}" == "--revert" ]]; then
  REVERT=1
fi

# ── Safety confirmation ──────────────────────────────────────────────────────
if [[ $REVERT -eq 0 ]]; then
  echo "⚠️  IBKR LIVE SWITCHOVER"
  echo "   This will:"
  echo "   1. Set ibc/config.ini TradingMode=live"
  echo "   2. Set ibkr_port=7496 in IBKR_CONTROL.csv"
  echo "   3. Restart ouroboros-ibkr-gateway-watch service"
  echo ""
  echo "   Daily loss limit: $(grep ibkr_daily_loss_limit_usd $IBKR_CONTROL | cut -d, -f2)"
  echo "   Max trades/day:   $(grep ibkr_max_trades_per_day $IBKR_CONTROL | cut -d, -f2)"
  echo ""
  read -r -p "Type 'GOLIVE' to confirm: " confirm
  if [[ "$confirm" != "GOLIVE" ]]; then
    echo "Aborted."
    exit 1
  fi
fi

# ── Apply changes ────────────────────────────────────────────────────────────
if [[ $REVERT -eq 1 ]]; then
  TARGET_MODE="paper"
  TARGET_PORT="7497"
  echo "↩️  Reverting to paper mode..."
else
  TARGET_MODE="live"
  TARGET_PORT="7496"
  echo "🚀 Switching to live mode..."
fi

# 1. Update IBC config.ini
if [[ -f "$IBC_CONFIG" ]]; then
  sed -i "s/^TradingMode=.*/TradingMode=$TARGET_MODE/" "$IBC_CONFIG"
  echo "   ✓ ibc/config.ini TradingMode=$TARGET_MODE"
else
  echo "   ⚠ $IBC_CONFIG not found, skipping"
fi

# 2. Update IBKR_CONTROL.csv port
python3 - <<PYEOF
import csv, io, pathlib

path = pathlib.Path("$IBKR_CONTROL")
rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
for row in rows:
    if row["key"] == "ibkr_port":
        row["value"] = "$TARGET_PORT"
out = io.StringIO()
w = csv.DictWriter(out, fieldnames=["key","value"])
w.writeheader()
w.writerows(rows)
path.write_text(out.getvalue(), encoding="utf-8")
print(f"   ✓ IBKR_CONTROL.csv ibkr_port=$TARGET_PORT")
PYEOF

# 3. Restart IB Gateway (picks up new TradingMode from config.ini)
sudo systemctl restart ouroboros-ibgateway
echo "   ✓ Restarted ouroboros-ibgateway (TradingMode=$TARGET_MODE)"

# 4. Restart bot
if systemctl is-active --quiet ouroboros-ibkr-bot 2>/dev/null; then
  sudo systemctl restart ouroboros-ibkr-bot
  echo "   ✓ Restarted ouroboros-ibkr-bot"
fi

echo ""
if [[ $REVERT -eq 1 ]]; then
  echo "✅ Paper mode restored."
else
  echo "✅ Live mode active. Monitor with: journalctl -u ouroboros-ibkr-bot -f"
  echo "   Emergency stop: sudo systemctl stop ouroboros-ibkr-bot"
  echo "                or: set ibkr_enabled=0 in IBKR_CONTROL.csv"
fi
