# /postmortem — シグナル事後分析エージェント

**役割**: 直近の決済トレードのシグナル品質を事後評価し、TP/SL・フィルター別の成功パターンを抽出する。
（tradermonty/claude-trading-skills `signal-postmortem` をOuroboros BTC FX向けに移植）

## データ取得コマンド

### 1. 直近30件の決済トレード詳細
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import csv, pathlib, json
from datetime import datetime, timedelta

logs_dir = pathlib.Path('/home/ubuntu/trading_bot/logs')

def calc_pnl(row):
    side = str(row.get('side','')).upper()
    try:
        entry = float(row.get('price') or 0)
        exit_p = float(row.get('ltp') or 0)
        size = float(row.get('size') or 0)
        if entry == 0: return None
        ppu = (exit_p - entry) if side == 'BUY' else (entry - exit_p)
        return ppu * size
    except: return None

trades = []
for i in range(90):
    d = datetime.now() - timedelta(days=i)
    f = logs_dir / f'trade_log_{d.strftime(\"%Y%m%d\")}.csv'
    if not f.exists(): continue
    for r in csv.DictReader(f.open()):
        result = str(r.get('result','')).strip()
        if result.startswith('PAPER_EXIT_'):
            r['_exit'] = result.replace('PAPER_EXIT_','')
            r['_pnl'] = calc_pnl(r)
            trades.append(r)

# 直近30件（新→旧）
closed = trades[:30]

tp_n = sum(1 for t in closed if t['_exit'] == 'TP')
sl_n = sum(1 for t in closed if t['_exit'] in ('SL','EARLY_ADVERSE'))
total = len(closed)
wr = tp_n / total * 100 if total else 0

tp_vals = [t['_pnl'] for t in closed if t['_exit'] == 'TP' and t['_pnl'] is not None]
sl_vals = [abs(t['_pnl']) for t in closed if t['_exit'] in ('SL','EARLY_ADVERSE') and t['_pnl'] is not None]
avg_win = sum(tp_vals)/len(tp_vals) if tp_vals else 0
avg_loss = sum(sl_vals)/len(sl_vals) if sl_vals else 0
payoff = avg_win / avg_loss if avg_loss > 0 else 0

print(f'=== 直近{total}件 事後分析 ===')
print(f'WR: {wr:.1f}%  TP={tp_n} SL={sl_n}')
print(f'平均利益: +¥{avg_win:.0f}  平均損失: -¥{avg_loss:.0f}  Payoff比: {payoff:.2f}')

# Kelly算出
if total >= 20:
    p = tp_n / total
    q = 1 - p
    b = payoff if payoff > 0 else 0.001
    kelly_full = (p * b - q) / b
    kelly_quarter = kelly_full * 0.25
    edge = p * b - q
    print()
    print(f'=== Kelly試算 (フル={kelly_full*100:.1f}%, 推奨1/4={kelly_quarter*100:.1f}%) ===')
    print(f'Edge={edge:.3f}  {"✅ 優位性あり" if edge > 0.02 else "⚠️  Edge薄い" if edge > 0 else "❌ 負のEdge"}')
else:
    print(f'(サンプル{total}件 < 20件 → Kelly不算出)')

print()
print('=== フィルター別 結果 ===')
# 時間帯別WR
by_hour = {}
for t in closed:
    h = str(t.get('time','00:00:00'))[11:13]
    by_hour.setdefault(h, {'tp':0,'sl':0})
    if t['_exit'] == 'TP': by_hour[h]['tp'] += 1
    else: by_hour[h]['sl'] += 1

for h in sorted(by_hour):
    tp = by_hour[h]['tp']; sl = by_hour[h]['sl']
    total_h = tp + sl
    wr_h = tp/total_h*100 if total_h else 0
    bar = '▓' * tp + '░' * sl
    print(f'  {h}時: WR={wr_h:.0f}% ({tp}TP/{sl}SL) {bar}')

print()
print('=== 出口種別 ===')
by_exit = {}
for t in closed:
    k = t['_exit']
    by_exit.setdefault(k, {'tp':0,'sl':0,'pnl':0.0})
    if t['_exit'] == 'TP': by_exit[k]['tp'] += 1
    else: by_exit[k]['sl'] += 1
    by_exit[k]['pnl'] += float(t['_pnl'] or 0) if t['_pnl'] is not None else 0

for reason, v in sorted(by_exit.items(), key=lambda x: -(x[1]['tp']+x[1]['sl'])):
    n = v['tp'] + v['sl']
    wr_r = v['tp']/n*100 if n else 0
    print(f'  {reason}: {n}件  WR={wr_r:.0f}%  累計¥{v[\"pnl\"]:+.0f}')
PYEOF"
```

### 2. 最悪ドローダウン分析
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import csv, pathlib
from datetime import datetime, timedelta

logs_dir = pathlib.Path('/home/ubuntu/trading_bot/logs')

def calc_pnl(row):
    side = str(row.get('side','')).upper()
    try:
        entry = float(row.get('price') or 0)
        exit_p = float(row.get('ltp') or 0)
        size = float(row.get('size') or 0)
        if entry == 0: return None
        ppu = (exit_p - entry) if side == 'BUY' else (entry - exit_p)
        return ppu * size
    except: return None

trades = []
for i in range(90):
    d = datetime.now() - timedelta(days=i)
    f = logs_dir / f'trade_log_{d.strftime(\"%Y%m%d\")}.csv'
    if not f.exists(): continue
    for r in csv.DictReader(f.open()):
        result = str(r.get('result','')).strip()
        if result.startswith('PAPER_EXIT_'):
            r['_exit'] = result.replace('PAPER_EXIT_','')
            r['_pnl'] = calc_pnl(r)
            trades.append(r)

trades = list(reversed(trades))  # 古い順
cum = 0.0
peak = 0.0
max_dd = 0.0
streak_sl = 0
max_streak = 0

for t in trades:
    pnl = float(t.get('_pnl') or 0) if t.get('_pnl') is not None else 0
    cum += pnl
    if cum > peak:
        peak = cum
    dd = peak - cum
    if dd > max_dd:
        max_dd = dd

    if t.get('_exit') in ('SL', 'EARLY_ADVERSE'):
        streak_sl += 1
        if streak_sl > max_streak:
            max_streak = streak_sl
    else:
        streak_sl = 0

print('=== ドローダウン分析 ===')
print(f'最大DD: ¥{max_dd:.0f}  最終累計: ¥{cum:+.0f}')
print(f'最大連敗: {max_streak}連敗')
if cum != 0:
    print(f'Calmar比率 (累計/最大DD): {abs(cum)/max_dd:.2f}' if max_dd > 0 else 'DD=0')
PYEOF"
```

## 出力フォーマット

```
【/postmortem】YYYY-MM-DD

直近N件サマリー
  WR: XX.X%  TP=XX SL=XX  Payoff=X.XX
  Edge=X.XXX  [✅優位性あり / ⚠️Edge薄い / ❌負のEdge]

Kelly試算
  フルKelly: XX.X%  推奨(1/4): X.X%
  ※サンプル不足の場合は最保守的な0.1x Kelly使用推奨

時間帯別WR
  10時: XX% (XTP/XSL)
  11時: ...

出口種別分析
  TP_normal: N件 WR=XX%
  SL_streak_stop: N件 WR=XX%

ドローダウン
  最大DD: ¥XXXX  最大連敗: X連敗
  Calmar: X.XX

推奨アクション
  - Edge > 0.10 かつ Payoff > 1.5 → 現パラメータ維持
  - Edge < 0.02 → SL/TPパラメータ見直しを検討
  - 時間帯別WRに5pt以上の差 → no_paper_hours調整を検討
```

## 判定基準（tradermonty backtest-expert準拠）

| 指標 | OK | WARN | NG |
|------|-----|------|-----|
| Edge | > 0.10 | 0.02〜0.10 | < 0.02 |
| Payoff比 | > 1.5 | 1.2〜1.5 | < 1.2 |
| 最大連敗 | ≤ 2 | 3 | ≥ 4 |
| Calmar | > 2.0 | 1.0〜2.0 | < 1.0 |
| サンプル数 | ≥ 50 | 20〜49 | < 20 |
