# /regime — 市場レジーム検出エージェント

**役割**: BTC FX市場の現在のボラティリティ・トレンド強度を2次元分類し、最適な戦略選択と
フィルター強度を提示する。
（agiprolabs/claude-trading-skills `regime-detection` をOuroboros BTC FX向けに移植）

## 4象限モデル

| 象限 | ボラ | トレンド | 状態 | 推奨 |
|------|------|---------|------|------|
| Q1 | Low  | Strong | **TREND-QUIET** | TP拡大・タイトSL有効 |
| Q2 | High | Strong | **TREND-VOLATILE** | SL広め・ロット据え置き |
| Q3 | Low  | Weak   | **RANGE-QUIET** | フィルター厳格化・様子見 |
| Q4 | High | Weak   | **RANGE-VOLATILE** | エントリー抑制推奨 |

## データ取得コマンド

### 1. 現在のATRパーセンタイル + ADX風トレンド強度
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import csv, pathlib, math
from datetime import datetime

ohlc_f = pathlib.Path('/home/ubuntu/trading_bot/MAIN/data/historical_ohlc.csv')
if not ohlc_f.exists():
    print('OHLCデータなし。/backtest でデータ取得を実行してください。')
    exit()

rows = list(csv.DictReader(ohlc_f.open()))
# 直近200本
rows = rows[-200:] if len(rows) >= 200 else rows
n = len(rows)

def to_float(v, default=0.0):
    try: return float(v)
    except: return default

# ATR計算（14期間）
atrs = []
for i in range(1, n):
    h = to_float(rows[i].get('high') or rows[i].get('h'))
    l = to_float(rows[i].get('low') or rows[i].get('l'))
    pc = to_float(rows[i-1].get('close') or rows[i-1].get('c'))
    tr = max(h - l, abs(h - pc), abs(l - pc))
    atrs.append(tr)

atr14 = sum(atrs[-14:]) / 14 if len(atrs) >= 14 else sum(atrs) / len(atrs) if atrs else 0
atr_history = []
for j in range(0, len(atrs) - 13):
    atr_history.append(sum(atrs[j:j+14]) / 14)

# ATRパーセンタイル（直近100期間）
atr_window = atr_history[-100:]
atr_percentile = sum(1 for a in atr_window if a < atr14) / len(atr_window) * 100 if atr_window else 50

# トレンド強度: EMA差分（trend_strength_er的簡易版）
closes = [to_float(r.get('close') or r.get('c')) for r in rows]
ema_fast = closes[-1]
ema_slow = closes[-1]
alpha_fast = 2/(10+1)
alpha_slow = 2/(30+1)
for c in reversed(closes[-50:]):
    ema_fast = alpha_fast * c + (1 - alpha_fast) * ema_fast
    ema_slow = alpha_slow * c + (1 - alpha_slow) * ema_slow

trend_pct = (ema_fast - ema_slow) / ema_slow * 100 if ema_slow > 0 else 0
adx_proxy = abs(trend_pct)  # 正規化トレンド強度

# Hurst指数（簡易）— RS法
def hurst(ts):
    if len(ts) < 20: return 0.5
    mean = sum(ts) / len(ts)
    deviations = [t - mean for t in ts]
    cumdev = []
    running = 0
    for d in deviations:
        running += d
        cumdev.append(running)
    R = max(cumdev) - min(cumdev)
    S = (sum((t - mean)**2 for t in ts) / len(ts)) ** 0.5
    if S == 0: return 0.5
    rs = R / S
    return math.log(rs) / math.log(len(ts)) if rs > 0 and len(ts) > 1 else 0.5

h_exp = hurst(closes[-50:])

# 象限判定
is_high_vol = atr_percentile > 75
is_trending = adx_proxy > 0.15  # EMAスプレッド0.15%以上でトレンドあり

if not is_high_vol and is_trending:     quadrant = 'Q1: TREND-QUIET   ✅ TP拡大・タイトSL有効'
elif is_high_vol and is_trending:       quadrant = 'Q2: TREND-VOLATILE ⚠️ SL広め推奨'
elif not is_high_vol and not is_trending: quadrant = 'Q3: RANGE-QUIET   ⚠️ フィルター厳格化'
else:                                   quadrant = 'Q4: RANGE-VOLATILE ❌ エントリー抑制'

print('=== 市場レジーム ===')
print(f'現在: {quadrant}')
print()
print(f'ATR(14):        {atr14:.0f} JPY')
print(f'ATRパーセンタイル: {atr_percentile:.0f}%  (>75%=高ボラ, <25%=低ボラ)')
print(f'EMAスプレッド:    {trend_pct:+.3f}%  (fast-slow / slow)')
print(f'Hurst指数:       {h_exp:.2f}  (<0.4=平均回帰, >0.6=トレンド継続)')
print()

# フィルター推奨
current_er_min = 0.30
if quadrant.startswith('Q1'):
    rec_er = 0.25
    rec_tp = '0.240%'
elif quadrant.startswith('Q2'):
    rec_er = 0.30
    rec_tp = '0.220%  (現状維持)'
elif quadrant.startswith('Q3'):
    rec_er = 0.35
    rec_tp = '0.190%  (縮小)'
else:
    rec_er = 0.40
    rec_tp = 'エントリー抑制推奨'

print(f'推奨 trend_strength_min_er: {rec_er}  (現在={current_er_min})')
print(f'推奨 TP目安: {rec_tp}')
PYEOF"
```

### 2. 直近2週間のレジーム推移サマリー
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import csv, pathlib
from datetime import datetime, timedelta

logs_dir = pathlib.Path('/home/ubuntu/trading_bot/logs')
print('=== 直近14日 日次ボラ・WR推移 ===')
for i in range(13, -1, -1):
    d = datetime.now() - timedelta(days=i)
    f = logs_dir / f'trade_log_{d.strftime(\"%Y%m%d\")}.csv'
    if not f.exists(): continue
    rows = list(csv.DictReader(f.open()))
    closed = [r for r in rows if r.get('outcome') in ('TP','SL')]
    tp = sum(1 for r in closed if r.get('outcome') == 'TP')
    sl = sum(1 for r in closed if r.get('outcome') == 'SL')
    pnl = sum(float(r.get('pnl_jpy') or 0) for r in closed)
    total = tp + sl
    wr = tp/total*100 if total else 0
    bar = '▓'*tp + '░'*sl
    icon = '✅' if wr >= 50 else '⚠️' if wr >= 39 else '❌' if total > 0 else '─'
    print(f'  {d.strftime(\"%m/%d\")} {icon} WR={wr:4.0f}% ({tp}T/{sl}S) P&L={pnl:+5.0f}円  {bar}')
PYEOF"
```

## 出力フォーマット

```
【/regime】YYYY-MM-DD HH:MM JST

現在レジーム: Q1: TREND-QUIET ✅ / Q2: TREND-VOLATILE ⚠️ / ...
ATR(14): XXX円  ATRパーセンタイル: XX%
EMAスプレッド: ±X.XXX%  Hurst: 0.XX (平均回帰/トレンド継続)

パラメータ推奨
  trend_strength_min_er: X.XX (現状→推奨)
  TP目安: X.XXX%

直近14日レジーム推移
  MM/DD ✅ WR=XX% (XTP/XS) P&L=+XXX円
  ...

アクション
  - Q1継続 → 現設定で維持
  - Q3移行 → ai_threshold一段引き上げ + ERフィルター強化を検討
```

## フィルター調整ガイド（レジーム連動）

| レジーム | `trend_strength_min_er` | `tp_*_pct` | `ai_threshold` |
|---------|------------------------|------------|----------------|
| Q1 TREND-QUIET | 0.25 (緩める) | 0.240 (拡大) | 0.75 |
| Q2 TREND-VOLATILE | 0.30 (維持) | 0.220 (維持) | 0.80 |
| Q3 RANGE-QUIET | 0.35 (締める) | 0.190 (縮小) | 0.82 |
| Q4 RANGE-VOLATILE | 0.40 (大幅締め) | 抑制 | 0.85 |
