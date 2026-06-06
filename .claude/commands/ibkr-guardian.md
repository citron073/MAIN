# /ibkr-guardian — IBKR 安全監視エージェント

**役割**: IBKR 米株ボットの日次 P&L・ポジション・損失限界・サービス稼働を安全確認する。

このコマンドを実行したら `ouroboros-ibkr-guardian` エージェントを起動し、以下のデータを取得・評価させてください。

## データ取得コマンド

### 1. IBKR state + 制御設定
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import json, csv, pathlib
from datetime import datetime

ROOT = pathlib.Path('/home/ubuntu/trading_bot/MAIN')

# ibkr_state.json
state_f = ROOT / 'ibkr_state.json'
state = json.loads(state_f.read_text()) if state_f.exists() else {}
updated = state.get('updated_at', 'N/A')
mode = state.get('mode', 'N/A')
pnl = state.get('daily_realized_pnl_usd', None)
open_pos = state.get('open_positions', {})

# IBKR_CONTROL.csv
ctrl = {}
for row in csv.reader((ROOT / 'IBKR_CONTROL.csv').open()):
    if len(row) >= 2: ctrl[row[0].strip()] = row[1].strip()

limit = float(ctrl.get('ibkr_daily_loss_limit_usd', -20))
enabled = ctrl.get('ibkr_enabled', '?')
port = ctrl.get('ibkr_port', '?')
max_trades = ctrl.get('ibkr_max_trades_per_day', '?')
tp = ctrl.get('ibkr_tp_pct', '?')
sl = ctrl.get('ibkr_sl_pct', '?')
vix_block = ctrl.get('ibkr_vix_block_threshold', '30')

print('=== IBKR 状態 ===')
print(f'更新: {updated}  mode={mode}  port={port}  enabled={enabled}')
print()
print(f'当日 P&L: \${pnl:.2f}' if pnl is not None else '当日 P&L: N/A')
if pnl is not None:
    remain = pnl - limit
    pct = pnl / abs(limit) * 100
    status = 'BREACH' if pnl <= limit else 'WARN' if pnl <= limit * 0.75 else 'OK'
    print(f'損失限界: \${limit:.0f}  使用: {abs(pct):.0f}%  残余: \${remain:+.2f}  [{status}]')
print()
print(f'オープンポジション: {len(open_pos)}件')
for sym, pos in open_pos.items():
    qty = pos.get('quantity', 0)
    avg = pos.get('avg_cost', 0)
    cur = pos.get('current_price') or avg
    unr = pos.get('unrealized_pnl', 0) or 0
    side = 'BUY' if qty > 0 else 'SELL'
    print(f'  {sym} {side} {qty}株 @ \${avg:.2f}  現在\${cur:.2f}  含み損益\${unr:+.2f}')
print()
print(f'設定: TP={tp}%  SL={sl}%  max_trades={max_trades}  vix_block={vix_block}')
PYEOF"
```

### 2. 今日の取引ログ
```bash
TODAY=$(date +%Y%m%d)
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "
f=/home/ubuntu/trading_bot/logs/ibkr_trade_log_${TODAY}.csv
if [ -f \"\$f\" ]; then
  echo '=== 今日のIBKR取引 ==='
  cat \"\$f\" | python3 -c \"
import csv, sys
rows = list(csv.DictReader(sys.stdin))
print(f'件数: {len(rows)}')
for r in rows:
  sym = r.get('symbol','?'); side = r.get('side','?')
  pnl = r.get('pnl_usd','?'); reason = r.get('exit_reason','?')
  t = r.get('time','?')
  print(f'  {t}  {sym} {side}  P&L=\${pnl}  理由={reason}')
\"
else
  echo '今日の取引ログなし'
fi"
```

### 3. サービス稼働確認
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "
echo '=== サービス稼働状況 ==='
for svc in ouroboros-ibkr-bot ouroboros-ibkr-gateway-watch; do
  status=\$(systemctl is-active \$svc 2>/dev/null || echo 'not-found')
  echo \"  \$svc: \$status\"
done
echo ''
echo '=== 直近エラーログ ==='
journalctl -u ouroboros-ibkr-bot --no-pager -n 20 2>/dev/null | grep -iE 'ERROR|WARN|disconnect|exception|traceback' | tail -8 || echo '(ログなし)'
"
```

## アラート閾値

| 条件 | レベル |
|------|--------|
| daily_realized_pnl_usd ≤ -15 (75%) | WARN |
| daily_realized_pnl_usd ≤ -20 | BREACH |
| ポジション保有 > 60分 TP/SLなし | STUCK |
| 3日以上取引0件 | 信号枯渇 |
| サービス停止 | DOWN |

## 安全ルール

- `ibkr_port` の変更（paper→live）は人間が行う
- `ibkr_enabled=0` が緊急停止手段
- 損失限界の緩和はユーザー承認必須
- `ibkr_shares` > 2 はユーザー承認必須

## 出力フォーマット

```
── IBKR 日次チェック ──────────────────────────────
日付: YYYY-MM-DD  mode=PAPER/LIVE  port=7496/7497
当日P&L: $XX.XX  限界: $-20.00  残余: $XX.XX  [OK/WARN/BREACH]

取引: X件  ポジション: X件
  [symbol] SIDE X株 @$XX.XX  含み$XX.XX

状態: OK / WARN / BREACH
────────────────────────────────────────────────
```
