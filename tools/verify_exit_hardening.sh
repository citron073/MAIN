#!/usr/bin/env bash
# IBKR 出口ハードニング(v2026.06.03.1)初稼働点検
# 使い方: bash MAIN/tools/verify_exit_hardening.sh   （米株寄付後の任意のタイミングで）
# VM(ouroboros-vm)へsshして4項目を確認し要約する。VMへの書込・再起動は一切しない。
set -uo pipefail
VM="ouroboros-vm"
DAY=$(TZ=Asia/Tokyo date +%Y%m%d)

echo "=== IBKR 出口ハードニング点検  ($(TZ=Asia/Tokyo date '+%Y-%m-%d %H:%M JST')) ==="

ssh -o ConnectTimeout=15 -o BatchMode=yes "$VM" "DAY=$DAY bash -s" <<'REMOTE'
cd /home/ubuntu/trading_bot/MAIN
OUT=review_out/ibkr_bot.systemd.out.log
LOG=../logs/ibkr_trade_log_${DAY}.csv

echo "--- (0) バージョン/サービス ---"
grep -m1 IBKR_BOT_VERSION ibkr_bot.py
echo "ActiveState: $(systemctl is-active ouroboros-ibkr-bot.service)"
systemctl show ouroboros-ibkr-bot.service -p NRestarts 2>/dev/null

echo "--- (1) 防御STP発注ログ（本日の最新10件） ---"
grep "protective STP" "$OUT" 2>/dev/null | tail -10 || echo "(なし=本日エントリーがまだ無い可能性)"
echo "STP発注エラー:"; grep "protective stop placement error" "$OUT" 2>/dev/null | tail -5 || echo "(なし)"

echo "--- (2) state: 建玉に防御STPが紐付いているか ---"
python3 - <<'PY'
import json
try:
    s=json.load(open("ibkr_state.json"))
    ops=s.get("open_positions",{})
    if not ops:
        print("open_positions: なし（建玉ゼロ。引け後/未エントリーなら正常）")
    for sym,p in ops.items():
        print(f"  {sym}: stop_id={p.get('protective_stop_order_id')} stop_price={p.get('stop_price')} side={p.get('side')} entry={p.get('entry_price')}")
    print("weekly_realized_pnl_usd:", s.get("weekly_realized_pnl_usd"))
except Exception as e:
    print("state読込エラー:", e)
PY

echo "--- (3) 本日の決済ログ（STOPFILL/EOD/STALE/SL/TP内訳） ---"
if [ -f "$LOG" ]; then
  echo "決済種別カウント:"; grep "_EXIT_" "$LOG" | sed -E 's/.*(LIVE|PAPER)_EXIT_([A-Z]+).*/\2/' | sort | uniq -c
  echo "STOPFILL明細:"; grep "STOPFILL" "$LOG" || echo "(なし)"
  echo "SL逸脱チェック(|fav|>0.6%):"; grep "_EXIT_SL" "$LOG" | grep -oE "current_fav=[-0-9.]+" || echo "(SLなし)"
else
  echo "本日ログ未生成（エントリーがまだ無い）"
fi

echo "--- (3.5) 円卓会議の活動（本日） ---"
if grep -q "^ibkr_council_enabled,1" IBKR_CONTROL.csv 2>/dev/null; then
  if [ -f "$LOG" ]; then
    confirmed=$(grep -cE ",(LIVE|PAPER)," "$LOG" 2>/dev/null); confirmed=${confirmed:-0}
    blocked=$(grep -c "COUNCIL_BLOCK" "$LOG" 2>/dev/null); blocked=${blocked:-0}
    echo "円卓会議=有効 / 本日 承認(エントリー)=${confirmed}  ブロック=${blocked}"
    if [ "${blocked:-0}" -gt 0 ]; then
      echo "ブロック理由トップ:"; grep "COUNCIL_BLOCK" "$LOG" | grep -oE "規律陣の拒否権|コア・セットアップ不成立|確信度不足|ALL-YESゲート不成立" | sort | uniq -c | sort -rn | head -3
    fi
  else
    echo "円卓会議=有効 / 本日まだエントリー判定なし"
  fi
else
  echo "円卓会議=無効(ibkr_council_enabled≠1)"
fi

echo "--- (4) 新コード由来のエラーのみ（接続リトライnoise除外） ---"
# adapter.connect() の ConnectionRefused は IB Gateway 起動待ちの既知noiseなので除外。
# 出口ハードニング/円卓会議の固有エラー文字列だけを拾う。
grep -E "position reconcile error|cancel protective stop error|protective stop placement error|council report error|StopOrder|investor_council" \
  review_out/ibkr_bot.systemd.err.log review_out/ibkr_bot.systemd.out.log 2>/dev/null | tail -8 \
  || echo "(自コード由来エラーなし)"
echo "errログ最終更新: $(date -r review_out/ibkr_bot.systemd.err.log '+%Y-%m-%d %H:%M' 2>/dev/null)（サービス起動より古ければデプロイ後エラーなし）"
REMOTE

echo "=== 点検完了 ==="
