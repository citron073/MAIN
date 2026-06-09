#!/bin/bash
# US場中(ET 平日 09:30-16:00)にport7496が閉じてたらntfy通知。30分dedupで連投防止。
set -uo pipefail
PORT=7496
NTFY_URL="https://ntfy.sh/ouroboros-Rdo5ZRinUQ5aIgZ6rZ4ghkla"
STATE=/home/ubuntu/trading_bot/MAIN/review_out/gateway_down_alert_state
ET_H=$(TZ=America/New_York date +%H); ET_M=$(TZ=America/New_York date +%M); ET_DOW=$(TZ=America/New_York date +%u)
mins=$((10#$ET_H*60 + 10#$ET_M))
# 平日(1-5)かつ 09:30(570分)-16:00(960分) ET のみ対象
if [ "$ET_DOW" -gt 5 ] || [ "$mins" -lt 570 ] || [ "$mins" -gt 960 ]; then exit 0; fi
# port開通=正常 → state消して終了
if nc -z 127.0.0.1 "$PORT" 2>/dev/null; then rm -f "$STATE"; exit 0; fi
# 30分以内に通知済みなら連投しない
now=$(date +%s)
if [ -f "$STATE" ]; then last=$(cat "$STATE" 2>/dev/null || echo 0); [ $((now-last)) -lt 1800 ] && exit 0; fi
curl -s -m 10 -X POST -H "Title: IBKR Gateway DOWN (US場中)" -H "Priority: urgent" -H "Tags: rotating_light" -d "US市場中にGatewayが落ちています(ET $(TZ=America/New_York date +%H:%M))。『起動し直して』で復旧してください。" "$NTFY_URL" > /dev/null 2>&1
echo "$now" > "$STATE"
