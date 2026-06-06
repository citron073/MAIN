#!/usr/bin/env bash
# 出口ハードニング自動点検＋ntfy通知（launchdから日次実行）
# verify_exit_hardening.sh を実行→要約をntfyへPOST→全文をreview_outへ保存。
# VMへの書込・再起動は一切しない（読み取りのみ）。
set -uo pipefail
ROOT="/Users/tani/trading_bot/trading_bot"
MAIN="$ROOT/MAIN"
REPORT_DIR="$MAIN/review_out"
mkdir -p "$REPORT_DIR"
STAMP=$(TZ=Asia/Tokyo date +%Y%m%d_%H%M)
REPORT="$REPORT_DIR/exit_verify_${STAMP}.log"

# 点検を実行して全文保存
bash "$MAIN/tools/verify_exit_hardening.sh" >"$REPORT" 2>&1

# 要約を組み立て
ACTIVE=$(grep -m1 "ActiveState:" "$REPORT" | awk '{print $2}')
NREST=$(grep -m1 "NRestarts=" "$REPORT" | tr -d ' ')
# grep -c は無マッチでも 0 を出力する。|| echo 0 は二重カウントになるので付けない。
STP_OK=$(grep -c "protective STP" "$REPORT"); STP_OK=${STP_OK:-0}
STP_ERR=$(grep -c "protective stop placement error" "$REPORT"); STP_ERR=${STP_ERR:-0}
STOPFILL=$(grep -c "_EXIT_STOPFILL" "$REPORT"); STOPFILL=${STOPFILL:-0}
SELF_ERR=$(grep -cE "position reconcile error|cancel protective stop error|council report error" "$REPORT"); SELF_ERR=${SELF_ERR:-0}
ENTRIES=$(grep -m1 "本日ログ未生成" "$REPORT" >/dev/null && echo "未エントリー" || echo "エントリーあり")
WKPNL=$(grep -m1 "weekly_realized_pnl_usd:" "$REPORT" | awk -F: '{print $2}' | xargs 2>/dev/null)
COUNCIL=$(grep -m1 "円卓会議=" "$REPORT" 2>/dev/null | sed 's# */ *詳細.*##')
[ -z "${COUNCIL:-}" ] && COUNCIL="円卓会議=不明"

# 無音事故の検出（2026-06-06追加: 鍵切れ等で2週間気づけなかった教訓）
# ① 失敗しているlaunchdジョブ（exit≠0）
FAILED_JOBS=$(launchctl list 2>/dev/null | grep -iE "ouroboros|altercore" | awk '$2 ~ /^[0-9]+$/ && $2+0 != 0 {print $3"(exit="$2")"}' | tr '\n' ' ')
FAILED_JOBS=${FAILED_JOBS:-なし}
# ② IBKRデータ同期の鮮度（直近2日のローカルログがあるか=同期が生きてるか）
FRESH=$(find "$MAIN/.local_llm/ibkr/logs" -name "ibkr_trade_log_*.csv" -mtime -2 2>/dev/null | wc -l | tr -d ' ')

# 健全性判定
FLAG="OK"
[ "$ACTIVE" != "active" ] && FLAG="⚠停止"
[ "$NREST" != "NRestarts=0" ] && FLAG="⚠再起動"
[ "${STP_ERR:-0}" -gt 0 ] && FLAG="⚠STP発注失敗"
[ "${SELF_ERR:-0}" -gt 0 ] && FLAG="⚠自コード例外"
[ "$FAILED_JOBS" != "なし" ] && FLAG="⚠ジョブ失敗"
[ "${FRESH:-0}" -eq 0 ] && FLAG="⚠データ同期停止"

BODY="[$FLAG] IBKR出口ハードニング点検
service=$ACTIVE $NREST
本日=$ENTRIES / STP発注=$STP_OK件 STP失敗=$STP_ERR件
STOPFILL=$STOPFILL件 自コード例外=$SELF_ERR件
$COUNCIL
失敗ジョブ: $FAILED_JOBS
IBKR同期(直近2日): ${FRESH}件
今週実現損益=\$${WKPNL}
詳細: $REPORT"

# ntfy へ通知（IBKR健全性なので株-Live優先。値は表示しない）
SECRETS="$MAIN/.streamlit/secrets.toml"
TOPIC=$(grep -m1 "^ntfy_stock_topic_url" "$SECRETS" 2>/dev/null | sed -E 's/.*=[[:space:]]*//' | tr -d '"'"'"' ')
[ -z "${TOPIC:-}" ] && TOPIC=$(grep -m1 "^ntfy_topic_url" "$SECRETS" 2>/dev/null | sed -E 's/.*=[[:space:]]*//' | tr -d '"'"'"' ')
if [ -n "${TOPIC:-}" ]; then
  curl -fsS -m 10 -H "Title: IBKR Exit Verify [$FLAG]" -d "$BODY" "$TOPIC" >/dev/null 2>&1 \
    && echo "ntfy sent" || echo "ntfy send failed"
else
  echo "ntfy_topic_url not found; skip notify"
fi

# macOS 通知（任意・失敗しても無視）
osascript -e "display notification \"service=$ACTIVE STP=$STP_OK STOPFILL=$STOPFILL\" with title \"IBKR Exit Verify [$FLAG]\"" 2>/dev/null || true

echo "$BODY"
