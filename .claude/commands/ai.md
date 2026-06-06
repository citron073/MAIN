# /ai — AIモデル監視エージェント

**役割**: AIモデルの鮮度・精度・自動学習状況を監視し、信頼度と再学習の必要性を判断する。

## データ取得コマンド

### 1. 現在のAIモデル状態
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import json, pathlib
from datetime import datetime

model = json.loads(pathlib.Path('/home/ubuntu/trading_bot/MAIN/ai_model.json').read_text())
info = model.get('model_info', {})
th = model.get('confidence_threshold', {})

last_day = info.get('auto_train_last_day') or info.get('last_updated', 'N/A')
if last_day and last_day != 'N/A':
    try:
        delta = (datetime.now().date() - datetime.fromisoformat(last_day).date()).days
        age_str = f'{delta}日前'
    except:
        age_str = '?'
else:
    age_str = '?'

rows_total  = info.get('auto_train_rows', 0)
rows_main   = info.get('auto_train_rows_main_raw', rows_total)
rows_shadow = info.get('auto_train_rows_shadow_raw', 0)
best_th     = info.get('auto_train_best_th', 'N/A')
base_th     = info.get('auto_train_base_th', 'N/A')
improve     = info.get('auto_train_improve', None)
applied     = info.get('auto_train_applied', False)
gate_pass   = info.get('auto_train_gate_pass_best', False)
gate_en     = info.get('auto_train_gate_enabled', False)
rollback    = info.get('auto_rollback_applied', False)
ai_enabled  = model.get('ai_enabled', False)
ai_mode     = model.get('ai_mode', 'N/A')

print('=== AI モデル状態 ===')
print(f'最終学習:     {last_day} ({age_str})')
print(f'サンプル数:   {rows_total}件  (MAIN:{rows_main} Shadow:{rows_shadow})')
print()
print(f'信頼度閾値:   entry={th.get(\"entry\", \"N/A\")}  extend={th.get(\"extend\", \"N/A\")}')
print(f'最適閾値:     base={base_th} → best={best_th}  改善={improve}  適用={applied}')
print(f'ゲート通過:   {gate_pass}  enabled={gate_en}')
print(f'ロールバック: {rollback}')
print()
print(f'ai_enabled={ai_enabled}  ai_mode={ai_mode}')
print(f'更新by:       {info.get(\"auto_updated_by\",\"N/A\")}  src={info.get(\"auto_train_source\",\"N/A\")}')
PYEOF"
```

### 2. 自動学習の実行ログ確認
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "
echo '=== daily-autotrain 直近 ==='
journalctl -u ouroboros-daily-autotrain.service --no-pager -n 30 2>/dev/null | grep -E 'Started|Finished|ERROR|OK|samples|wr=|th=' | tail -10

echo ''
echo '=== champion-gate 直近 ==='
journalctl -u ouroboros-champion-gate.service --no-pager -n 30 2>/dev/null | grep -E 'Started|Finished|promote|hold|block|wr=' | tail -8

echo ''
echo '=== weekly-autotrain 直近 ==='
journalctl -u ouroboros-weekly-autotrain.service --no-pager -n 30 2>/dev/null | grep -E 'Started|Finished|ERROR|OK|shadow' | tail -8
"
```

### 3. Shadow学習組み込み状況
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import csv, pathlib, json

ctrl = {}
for row in csv.reader(open('/home/ubuntu/trading_bot/MAIN/CONTROL.csv')):
    if len(row) >= 2: ctrl[row[0].strip()] = row[1].strip()

print('=== AI学習設定 ===')
print(f'ai_auto_train_enabled:     {ctrl.get(\"ai_auto_train_enabled\", \"N/A\")}')
print(f'ai_train_include_shadow:   {ctrl.get(\"ai_train_include_shadow\", \"N/A\")}')
print(f'ai_train_shadow_boost:     {ctrl.get(\"ai_train_shadow_boost\", \"N/A\")}')
print(f'ai_gate_pf_min:            {ctrl.get(\"ai_gate_pf_min\", \"N/A\")}')
print(f'ai_gate_min_samples:       {ctrl.get(\"ai_gate_min_samples\", \"N/A\")}')
print(f'ai_monthly_reval_enabled:  {ctrl.get(\"ai_monthly_reval_enabled\", \"N/A\")}')
print()
print(f'good_hours boost: {ctrl.get(\"ai_train_weekly_good_hours\",\"N/A\")} x{ctrl.get(\"ai_train_weekly_good_hour_boost\",\"1.2\")}')
print(f'bad_hours penalty: {ctrl.get(\"ai_train_weekly_bad_hours\",\"N/A\")} x{ctrl.get(\"ai_train_weekly_bad_hour_penalty\",\"0.7\")}')

state = json.loads(pathlib.Path('/home/ubuntu/trading_bot/MAIN/state.json').read_text())
waf = state.get('_weekly_auto_feedback', {}) or {}
si = waf.get('shadow_inclusion', {}) or {}
print()
print('=== Shadow自動inclusion直近結果 ===')
print(f'action: {si.get(\"action\", \"N/A\")}')
print(f'reason: {si.get(\"reason\", \"N/A\")}')
PYEOF"
```

### 4. バックテスト学習状況
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import csv, pathlib

bt_log = pathlib.Path('/home/ubuntu/trading_bot/logs/backtest/ai_training_log_backtest.csv')
ctrl = {}
for row in csv.reader(open('/home/ubuntu/trading_bot/MAIN/CONTROL.csv')):
    if len(row) >= 2: ctrl[row[0].strip()] = row[1].strip()

ohlc = pathlib.Path('/home/ubuntu/trading_bot/MAIN/data/historical_ohlc.csv')
print('=== バックテスト学習状況 ===')
if ohlc.exists():
    rows = list(csv.DictReader(open(ohlc)))
    ts = sorted(r.get('ts','') or r.get('timestamp','') for r in rows if r.get('ts') or r.get('timestamp'))
    if ts:
        print(f'OHLCデータ: {len(rows):,}本  期間: {ts[0][:10]}〜{ts[-1][:10]}')
    else:
        print(f'OHLCデータ: {len(rows):,}本 (タイムスタンプ不明)')
else:
    print('OHLCデータ: なし (tools/fetch_historical_ohlc.py を実行してください)')

if bt_log.exists():
    rows = list(csv.DictReader(open(bt_log)))
    tp = sum(1 for r in rows if r.get('outcome') == 'TP')
    sl = sum(1 for r in rows if r.get('outcome') == 'SL')
    total = len(rows)
    wr = tp/total*100 if total > 0 else 0
    wins   = [float(r.get('ret_pct',0)) for r in rows if float(r.get('ret_pct',0)) > 0]
    losses = [abs(float(r.get('ret_pct',0))) for r in rows if float(r.get('ret_pct',0)) < 0]
    pf = sum(wins)/sum(losses) if losses and sum(losses) > 0 else 0
    gate   = ctrl.get('ai_train_backtest_gate_min_samples', '300')
    pf_gate = ctrl.get('ai_train_backtest_gate_pf_min', '1.0')
    incl   = ctrl.get('ai_train_include_backtest', '0')
    print(f'バックテストサンプル: {total}件  WR={wr:.1f}%  PF={pf:.3f}')
    print(f'  gate: samples>={gate} [{\"OK\" if total>=int(gate) else \"不足\"}]  PF>={pf_gate} [{\"OK\" if pf>=float(pf_gate) else \"不足\"}]')
    print(f'  ai_train_include_backtest={incl}  boost={ctrl.get(\"ai_train_backtest_boost\",\"0.30\")}')
else:
    print('バックテストサンプル: なし')
PYEOF"
```

### 5. 実績 vs 訓練 乖離チェック（直近30日）
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import csv, pathlib, json
from datetime import datetime, timedelta

logs_dir = pathlib.Path('/home/ubuntu/trading_bot/logs')
tp, sl = 0, 0
for i in range(30):
    d = datetime.now() - timedelta(days=i)
    f = logs_dir / f'trade_log_{d.strftime(\"%Y%m%d\")}.csv'
    if not f.exists(): continue
    for r in csv.reader(f.open()):
        if len(r) < 2: continue
        if 'TP' in r[1]: tp += 1
        if 'SL' in r[1]: sl += 1

actual_wr = tp/(tp+sl)*100 if (tp+sl) > 0 else None
model = json.loads(pathlib.Path('/home/ubuntu/trading_bot/MAIN/ai_model.json').read_text())
info = model.get('model_info', {})
best_th      = info.get('auto_train_best_th', None)
base_metric  = info.get('auto_train_base_metric', None)
best_metric  = info.get('auto_train_best_metric', None)
th_entry     = model.get('confidence_threshold', {}).get('entry', 'N/A')

print('=== 実績 vs 学習状況 (直近30日) ===')
if actual_wr:
    print(f'実績WR: {actual_wr:.1f}% (TP={tp} SL={sl})')
    status = '正常範囲' if actual_wr >= 44 else '要監視' if actual_wr >= 39 else '要対応(BE割れ)'
    print(f'判定:   {status}  (目標>44% / BE=39%)')
else:
    print('実績WR: N/A (取引なし)')
print(f'閾値:   entry={th_entry}  最適化後best_th={best_th}')
print(f'metric: base={base_metric}  best={best_metric}')
PYEOF"
```

### 6. 週次WR時系列（直近4週）
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import csv, pathlib
from datetime import datetime, timedelta

logs_dir = pathlib.Path('/home/ubuntu/trading_bot/logs')
today = datetime.now()
print('=== 週次WR推移（直近4週） ===')
for week in range(4):
    start = today - timedelta(days=(week+1)*7)
    end   = today - timedelta(days=week*7)
    tp, sl = 0, 0
    for i in range(7):
        d = start + timedelta(days=i)
        f = logs_dir / f'trade_log_{d.strftime(\"%Y%m%d\")}.csv'
        if not f.exists(): continue
        for r in csv.reader(f.open()):
            if len(r) < 2: continue
            if 'TP' in r[1]: tp += 1
            if 'SL' in r[1]: sl += 1
    total = tp + sl
    wr = tp/total*100 if total > 0 else None
    label = f'{start.strftime(\"%m/%d\")}〜{(end - timedelta(days=1)).strftime(\"%m/%d\")}'
    icon = 'OK' if wr and wr >= 44 else 'WARN' if wr and wr >= 38 else 'NG' if wr else '-'
    wr_str = f'{wr:.1f}% (TP={tp} SL={sl})' if wr else f'N/A (TP={tp} SL={sl})'
    print(f'  [{icon}] {[\"今週\",\"先週\",\"2週前\",\"3週前\"][week]} ({label}): {wr_str}')
PYEOF"
```

## 出力フォーマット

```
【AI担当レポート】YYYY-MM-DD HH:MM JST

モデル状態
  最終学習: YYYY-MM-DD (N日前)  サンプル: XXX件 (MAIN:XX Shadow:XX)
  閾値: entry=0.80  最適化: base=0.73→best=0.70  適用=True
  ai_enabled=False  mode=ADVISORY

実績 vs 学習
  直近30日 実績WR: XX.X% (TP=XX SL=XX)
  判定: 正常範囲 / 要監視 / 要対応

自動学習
  daily-autotrain: 最終実行 YYYY-MM-DD  成功/失敗
  shadow inclusion: include/exclude
```

## 判定基準

| 指標 | OK | WARN | NG |
|------|-----|------|-----|
| 経過日数 | <14日 | 14〜30日 | >30日 |
| サンプル数 | ≥150件 | 100〜149件 | <100件 |
| 実績WR | ≥44% | 39〜43% | <39% |
| gate_pass | True | - | False |
