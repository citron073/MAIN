# /kelly — Kelly基準ポジションサイジング

**役割**: Ouroboros BTC FX + IBKR QQQ のEdge強度をKelly基準で算出し、
最適ロット・リスク比率を提示する。
（agiprolabs/claude-trading-skills `kelly-criterion` をOuroboros向けに移植）

## Kelly公式

```
f* = (p * b - q) / b

p = 勝率  q = 1 - p  b = Payoff比 (平均利益 / 平均損失)
実用: f*_quarter = f* * 0.25  (推奨使用倍率)
```

**重要**: EdgeがゼロまたはマイナスならKelly=0 → 当該システムはトレードしない。

## データ取得コマンド

### 1. BTC FX Kelly計算（直近60日実績）
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import csv, pathlib, math
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
            exit_type = result.replace('PAPER_EXIT_','')
            r['_exit'] = exit_type
            r['_pnl'] = calc_pnl(r)
            trades.append(r)

tp_pnl = [t['_pnl'] for t in trades if t['_exit'] == 'TP' and t['_pnl'] is not None]
sl_pnl = [abs(t['_pnl']) for t in trades if t['_exit'] in ('SL','EARLY_ADVERSE') and t['_pnl'] is not None]
n = len(tp_pnl) + len(sl_pnl)

print('=== BTC FX Kelly分析 ===')
print(f'サンプル: {n}件  (TP={len(tp_pnl)} SL={len(sl_pnl)})')
if n < 20:
    print('サンプル不足 (<20件) → 0.10x Kelly推奨（最保守）')
else:
    p = len(tp_pnl) / n
    avg_win = sum(tp_pnl) / len(tp_pnl) if tp_pnl else 0
    avg_loss = sum(sl_pnl) / len(sl_pnl) if sl_pnl else 1
    b = avg_win / avg_loss if avg_loss > 0 else 0
    edge = p * b - (1 - p)
    kelly_full = edge / b if b > 0 else 0
    
    # Wilson下限（保守的p推定）
    z = 1.96
    denominator = 1 + z**2 / n
    centre = p + z**2 / (2 * n)
    spread = z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n)
    p_conservative = (centre - spread) / denominator
    edge_cons = p_conservative * b - (1 - p_conservative)
    kelly_cons = edge_cons / b if b > 0 else 0
    
    # 推奨倍率
    if n >= 100 and edge > 0.10:
        rec_frac = 0.50; rec_label = '0.50x (高信頼)'
    elif n >= 50 and edge > 0.05:
        rec_frac = 0.25; rec_label = '0.25x (標準)'
    elif n >= 20 and edge > 0.02:
        rec_frac = 0.10; rec_label = '0.10x (保守)'
    else:
        rec_frac = 0.10; rec_label = '0.10x (Edge薄い)'
    
    print()
    print(f'勝率(実績):  {p*100:.1f}%')
    print(f'勝率(保守):  {p_conservative*100:.1f}% (Wilson下限)')
    print(f'Payoff比:    {b:.3f}  (平均利益¥{avg_win:.0f} / 平均損失¥{avg_loss:.0f})')
    print(f'Edge:        {edge:.4f}  /  保守Edge: {edge_cons:.4f}')
    print()
    print(f'フルKelly:   {kelly_full*100:.1f}%')
    if kelly_cons > 0:
        print(f'推奨({rec_label}): {kelly_cons*rec_frac*100:.1f}% の資金をリスクにさらす')
    else:
        print(f'推奨: ⚠️  保守的Edgeがマイナス → 固定最小ロット維持（サンプル蓄積中）')
        print(f'  Wilson下限WR={p_conservative*100:.1f}% → Edgeの統計的確認にはあと{max(0, 200-n)}件必要')
    print()
    
    if edge <= 0:
        print('❌ Edgeがゼロ以下 → このシステムはトレードしてはいけない状態')
    elif kelly_cons <= 0:
        print('⚠️  点推定Edgeはプラスだが統計的確認不足 → 固定最小ロット維持')
        print(f'  目安: サンプル{max(200, n+50)}件達成後に再評価')
    elif edge < 0.10:
        print('✅  Marginal Edge → 0.10x Kelly以下で運用継続')
    else:
        print('✅  Good Edge → 0.25x Kelly推奨')
    
    print()
    # 現在の設定との整合性チェック
    print('=== 現設定との整合 ===')
    config_payoff = 0.220 / 0.140
    print(f'現在 TP=0.220%  SL=0.140%  →  設定Payoff={config_payoff:.2f}')
    print(f'実績Payoff比: {b:.2f}  差分: {b - config_payoff:+.2f}')
    if b < config_payoff * 0.85:
        print('⚠️  実績Payoffが設定を15%以上下回る → 早期出口・部分約定の影響あり')
PYEOF"
```

### 2. IBKR QQQ Kelly計算
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import csv, pathlib, math
from datetime import datetime, timedelta

logs_dir = pathlib.Path('/home/ubuntu/trading_bot/logs')
trades = []
for i in range(60):
    d = datetime.now() - timedelta(days=i)
    f = logs_dir / f'ibkr_trade_log_{d.strftime(\"%Y%m%d\")}.csv'
    if not f.exists(): continue
    for r in csv.DictReader(f.open()):
        trades.append(r)

tp_pnl = [float(t.get('pnl_usd') or 0) for t in trades if float(t.get('pnl_usd') or 0) > 0]
sl_pnl = [abs(float(t.get('pnl_usd') or 0)) for t in trades if float(t.get('pnl_usd') or 0) < 0]
n = len(tp_pnl) + len(sl_pnl)

print('=== IBKR QQQ Kelly分析 ===')
print(f'サンプル: {n}件  (TP={len(tp_pnl)} SL={len(sl_pnl)})')
if n < 10:
    print('サンプル不足 (<10件) → 0.10x Kelly推奨（最保守）')
    print(f'設定ベースKelly: TP=0.5% SL=0.25% → 設定Payoff=2.0')
    print(f'  WR仮定50%→ Edge={0.5*2.0-0.5:.2f}  フルKelly={0.5*2.0-0.5/2.0*100:.1f}%')
else:
    p = len(tp_pnl) / n
    avg_win = sum(tp_pnl) / len(tp_pnl) if tp_pnl else 0.5
    avg_loss = sum(sl_pnl) / len(sl_pnl) if sl_pnl else 0.25
    b = avg_win / avg_loss
    edge = p * b - (1 - p)
    kelly_full = edge / b if b > 0 else 0
    
    print(f'勝率: {p*100:.1f}%  Payoff: {b:.2f}  Edge: {edge:.3f}')
    print(f'フルKelly: {kelly_full*100:.1f}%  推奨0.25x: {kelly_full*0.25*100:.1f}%')
PYEOF"
```

## 出力フォーマット

```
【/kelly】YYYY-MM-DD

BTC FX (直近60日 N件)
  勝率: XX.X% (実績) / XX.X% (Wilson保守下限)
  Payoff: X.XX  Edge: X.XXXX
  フルKelly: XX.X%
  推奨(0.25x): X.X% → 証拠金XXX万の X.X% = XX円リスク/トレード
  判定: ✅ Good / ⚠️ Marginal / ❌ Negative Edge

IBKR QQQ
  WR: XX%  Payoff: X.XX  Edge: X.XXX
  推奨(0.10x): X.X%

注意事項
  - Kellyはサンプル50件以上で有効（現在X件）
  - Edgeがマイナスなら即パラメータ見直し
  - 実績Payoffが設定Payoffを下回る場合はfill rate確認
```

## Edgeとフィルター調整の関係

| Edge | 推奨 Kelly倍率 | アクション |
|------|--------------|---------|
| > 0.20 | 0.50x | 現設定で自信あり |
| 0.10–0.20 | 0.25x | 現設定維持・様子見 |
| 0.02–0.10 | 0.10x | パラメータ微調整 |
| 0–0.02 | 0.10x | SL/TP比の見直し |
| < 0 | 0 | 即座にパラメータ見直し |

**ルール**: Kelly倍率の変更はサンプルが2倍になるまで待つ。焦って変更しない。
