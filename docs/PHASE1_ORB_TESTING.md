# Phase 1: Opening Range Breakout (ORB) - 実装・テスト・デプロイ

> 実装日: 2026-05-08  
> 対象: ibkr_bot.py + IBKR_CONTROL.csv  
> 状態: ✅ PAPER検証中（予定期間: 1-2週間）

---

## 実装内容

### 追加コンポーネント

| 関数 | 役割 |
|------|------|
| `_calc_opening_range()` | 寄り付き15分間のORB計算（高値・安値） |
| `_calc_vwap()` | 日中VWAPの計算 |
| `_get_avg_volume()` | 直近N本の平均出来高計算 |
| `_check_orb_breakout()` | ORB上/下抜けとボリュームフィルタチェック |

### ロジック

```
1. 寄り付き後のbarから opening_range を計算（15分）
   ├─ high = 最高値
   └─ low = 最安値

2. 9:45 ET 以降、毎分チェック
   ├─ current_close > orb_high + 出来高確認 → BUY
   └─ current_close < orb_low + 出来高確認 → SELL

3. VWAP がorb_high/orb_low方向と一致確認

4. Signal: BUY/SELL/None
```

### IBKR_CONTROL.csv の設定

```csv
ibkr_setup_orb_enabled,1
ibkr_setup_orb_lookback_min,15
ibkr_setup_orb_volume_threshold,1.5
ibkr_setup_orb_use_vwap,1
```

### Signal Priority

```
現在: SMA signal OR ORB signal
優先度: ORB > SMA（ORB有効時）
```

---

## 手動テスト（ローカルPAPER）

### Step 1: ローカル構文確認

```bash
cd /Users/tani/trading_bot/trading_bot/MAIN
python3 -m py_compile ibkr_bot.py
# ✅ OK なら続行
```

### Step 2: VM で PAPER 実行テスト

```bash
# VM: ibkr_bot を実行（既存スケジュール通り）
# または手動: python3 ibkr_bot.py

# 出力を確認
tail -f /home/ubuntu/trading_bot/logs/ibkr_trade_log_*.csv

# "setup=ORB" というフィールドが見えたら成功
```

### Step 3: ダッシュボード確認

```
http://localhost:8501 (ローカルダッシュボード)
→ IBKR US株 タブ
→ "最新セッションレビュー" 
→ ORB シグナル表示確認
```

### Step 4: ログ解析

```bash
# trade_log_YYYYMMDD.csv を確認
grep "setup=ORB" /home/ubuntu/trading_bot/logs/ibkr_trade_log_*.csv

# 以下の項目を確認:
# - setup=ORB
# - setup_details に {"orb_high": X, "orb_low": Y, "vwap": Z}
# - entry_price の妥当性
```

---

## PAPER 検証期間（1-2週間）

### 毎日チェックリスト

- [ ] ORB シグナルが発火しているか
- [ ] ORB シグナルの WR（勝率）を記録
- [ ] false positives（誤発火）がないか確認
- [ ] ログに setup_details が正確に記録されているか

### 集計ポイント

```
期間: ≥5営業日

指標:
1. WR (Win Rate)
   - ORB シグナルのうち TP達成率
   - 目安: ≥40% なら継続、<35% なら調整

2. Count
   - ORB シグナル発火数
   - 期待値: 1日 1-3 回（市場環境による）

3. FP (False Positive)
   - すぐに逆行した回数
   - 出来高フィルタで削減可能か検討

4. Slippage
   - entry_price と current_price の差
   - 約定環境の確認
```

### 問題判定基準

| 症状 | 対応 |
|------|------|
| WR < 30% | `ibkr_setup_orb_enabled=0` で無効化、パラメータ調整へ |
| 毎日10+回 誤発火 | `volume_threshold` を 1.5 → 2.0 へ上げる |
| VWAPが不正確 | `ibkr_setup_orb_use_vwap=0` で一時無効化 |
| オーバーフィット疑い | サンプル拡大（2-3週間続行） |

---

## ロールバック手順

問題が発生した場合:

```bash
# 1. ORB 無効化（即時）
# IBKR_CONTROL.csv:
ibkr_setup_orb_enabled,0

# 2. VM でボット再起動
ssh ubuntu@161.33.26.35
sudo systemctl restart ouroboros-ibkr-bot.service

# 3. SMA のみで稼働確認
tail -f /home/ubuntu/trading_bot/logs/ibkr_trade_log_*.csv
# setup=SMA が出ていればOK
```

---

## 次Phase への進級条件

Phase 2 (Dip and Rip) へ進むには:

```
✅ 5営業日以上の実績
✅ WR ≥ 40%
✅ false positive ≤ 20%
✅ ログ記録に誤りなし
✅ ダッシュボール表示OK
```

すべて満たしたら、次の手順でPhase 2へ：

```
1. Phase 2 の IBKR_CONTROL.csv パラメータ追加
2. ibkr_bot.py に Dip & Rip 検出ロジック追加
3. テスト 1-2週間
```

---

## デバッグTips

### ORB がまったく発火しない

```python
# 1. ORB range が計算されているか確認
print(f"ORB high={orb_range['high']}, low={orb_range['low']}")

# 2. bars の時刻を確認（9:30 ETから15分分あるか）
for b in bars[-20:]:
    print(f"time={b['time']}, high={b['high']}, low={b['low']}, vol={b['volume']}")

# 3. Lookback window を短くしてテスト
ibkr_setup_orb_lookback_min,10  # 15 → 10に短縮
```

### ORB が出ても WR が悪い

```python
# 1. volume_threshold を上げる（誤発火削減）
ibkr_setup_orb_volume_threshold,2.0  # 1.5 → 2.0

# 2. VWAP フィルタを厳しく
ibkr_setup_orb_use_vwap,1  # 有効化確認

# 3. 時間帯制限を追加
# 9:45–10:30 ET のみ、または
# 16:00 ET（EOD） 手前のノイズ除外
```

### ログに setup_details が出ない

```bash
# JSON encode エラーの可能性
# 確認：
tail -f ibkr_trade_log_*.csv | grep setup_details

# 出ていなければ、ログ記録側のエラーをVM stderr で確認
```

---

## ファイル変更サマリー

### ibkr_bot.py
- `_calc_opening_range()` 追加
- `_calc_vwap()` 追加
- `_get_avg_volume()` 追加
- `_check_orb_breakout()` 追加
- `run_once()` の signal 生成ロジック更新（ORB優先）
- trade_log に `setup=ORB` フィールド追加

### IBKR_CONTROL.csv
- `ibkr_setup_mode,multi`
- `ibkr_setup_orb_enabled,1`
- `ibkr_setup_orb_lookback_min,15`
- `ibkr_setup_orb_volume_threshold,1.5`
- `ibkr_setup_orb_use_vwap,1`
- Phase 2-4 設定（無効化）

---

## 次のステップ

✅ Phase 1 実装完了  
⏳ Phase 1 PAPER検証: 1-2週間  
📋 Phase 2 (Dip & Rip) 準備中

