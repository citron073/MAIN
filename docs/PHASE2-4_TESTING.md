# IBKR米株デイトレ全Setupsペーパー実装・テスト完全ガイド

> 完成日: 2026-05-08  
> 対象: Phase 1-4 (ORB, Dip & Rip, VCP, Momentum)  
> 状態: ✅ PAPER検証開始準備完了  
> テスト期間: 段階的 1-2週間 × 各Phase

---

## 実装状態チェックリスト

### コード側

- [x] `ibkr_bot.py` に Phase 1-4 の検出関数を追加
- [x] `run_once()` のシグナル生成ロジックを更新（優先度制御）
- [x] 各Setupのログに `setup=XXX` を記録
- [x] 構文チェック: ✅ OK

### 設定側

- [x] `IBKR_CONTROL.csv` にすべてのパラメータを追加
- [x] Phase 1: 有効化 (`enabled=1`)
- [x] Phase 2-4: 無効化 (`enabled=0`)

### ドキュメント側

- [x] `docs/IBKR_DAYTRADE_SETUP_PLAN.md` — 全5Phaseロードマップ
- [x] `docs/PHASE1_ORB_TESTING.md` — Phase 1 詳細ガイド
- [x] `docs/IBKR_AGENT_SPEC.md` — サブエージェント仕様（更新済み）
- [x] このドキュメント — 統合テスト・デプロイガイド

---

## 段階的テスト進行フロー

```
┌──────────────────────────────────┐
│ Phase 1: ORB (現在実装中)         │
│ enabled=1  ← PAPER検証開始        │
│期限: 1-2週間                     │
└──────────────────────────────────┘
          ↓ (WR≥40% + FP<20% 達成)
┌──────────────────────────────────┐
│ Phase 2: Dip & Rip               │
│ enabled=0 ← 手動で enabled=1に設定│
│期限: 1-2週間                     │
└──────────────────────────────────┘
          ↓ (条件達成)
┌──────────────────────────────────┐
│ Phase 3: Intraday VCP            │
│ enabled=0 ← 手動で enabled=1に設定│
│期限: 1-2週間                     │
└──────────────────────────────────┘
          ↓ (条件達成)
┌──────────────────────────────────┐
│ Phase 4: Momentum Breakout       │
│ enabled=0 ← 手動で enabled=1に設定│
│期限: 1-2週間                     │
└──────────────────────────────────┘
```

---

## Phase 2: Dip and Rip - テスト開始手順

### 条件: Phase 1 達成後

```
Phase 1 結果:
✅ WR ≥ 40%
✅ False Positive ≤ 20%
✅ ログ記録に誤りなし
✅ 5営業日以上の実績
```

### 手順

**1. 設定値を確認・調整**

```bash
cd /Users/tani/trading_bot/trading_bot/MAIN
grep "dip_rip\|gap_threshold\|retrace" IBKR_CONTROL.csv
```

現在の設定:
```
ibkr_setup_dip_rip_enabled,0
ibkr_setup_dip_rip_gap_threshold,1.5
ibkr_setup_dip_rip_vwap_retrace_pct,2.0
```

**2. Phase 2 有効化**

```bash
# IBKR_CONTROL.csv を編集
ibkr_setup_dip_rip_enabled,1
```

**3. VM でボット再起動**

```bash
ssh ubuntu@161.33.26.35
sudo systemctl restart ouroboros-ibkr-bot.service

# 確認
tail -f /home/ubuntu/trading_bot/logs/ibkr_trade_log_*.csv | grep "setup="
```

**4. PAPER テスト開始（≥5営業日）**

ログを監視:
```bash
# DIP_RIP シグナルを検出
grep "setup=DIP_RIP" /home/ubuntu/trading_bot/logs/ibkr_trade_log_*.csv

# 統計情報
WR、FP、エントリー数 を毎日記録
```

### テスト期間の判定基準

| 指標 | 合格 | 保留 | 不合格 |
|------|------|------|--------|
| WR | ≥40% | 35-40% | <35% |
| FP | ≤20% | 20-30% | >30% |
| サンプル | ≥5件 | 3-5件 | <3件 |

---

## Phase 3: Intraday VCP - テスト開始手順

### 条件: Phase 2 達成後

```
Phase 2 結果:
✅ WR ≥ 40%
✅ False Positive ≤ 20%
✅ ≥5営業日実績
```

### セットアップの性質

```
VCP = 値幅収縮パターン
- 強い上昇後、高値圏で横ばい
- 押し幅が段階的に縮小 (3% → 1.8% → 0.8%)
- 出来高が減少（売り圧減弱）
- 最後に出来高付き上抜け

特徴: 待つ必要がある（すぐには発火しない）
      リスク: 低め（圧縮完成後の上抜けのみ）
      リターン: 中～高
```

### 手順

**1. パラメータ確認**

```bash
grep "vcp\|lookback" IBKR_CONTROL.csv
```

現在:
```
ibkr_setup_vcp_lookback,10
ibkr_setup_vcp_volume_threshold,1.5
```

**2. Phase 3 有効化**

```bash
# IBKR_CONTROL.csv を編集
ibkr_setup_vcp_enabled,1
```

**3. VM 再起動 → PAPER テスト（≥5営業日）**

### テスト注意点

- VCP は「待ち」のパターン → エントリー数が少ない可能性
- サンプル不足の場合は 2-3週間まで延長してOK
- Lookback 期間を変更してみる（10 → 5 または 15）

---

## Phase 4: Momentum Breakout - テスト開始手順

### 条件: Phase 3 達成後

### セットアップの性質

```
Momentum = 急騰・追随買い
- 出来高が3倍以上に急増
- 価格が2%以上の急上昇
- VWAP を抜けて上昇

特徴: リスク最高、リターン最大
      「今すぐ」発火 → 高速約定必須
      踏み上げリスク、ハルト風　要注意
```

### 手順

**1. パラメータ確認**

```bash
grep "momentum" IBKR_CONTROL.csv
```

現在:
```
ibkr_setup_momentum_volume_surge_ratio,3.0
ibkr_setup_momentum_min_move_pct,2.0
```

**2. Phase 4 有効化**

```bash
ibkr_setup_momentum_enabled,1
```

**3. PAPER テスト（≥5営業日、慎重に）**

### テスト時の注意

- **最高リスク** — WR が40%未満なら即停止
- **約定滑り** — 市場が激しい時期は期待値マイナス化
- **ハルト** — 急騰銘柄はハルトが頻繁
- サンプルは少なくなる傾向

---

## 全Phase統合後のパラメータセット

すべてのPhaseを通過した場合、こんな設定になる:

```csv
# ORB（最も信頼性高い）
ibkr_setup_orb_enabled,1

# Dip & Rip（親和性高い）
ibkr_setup_dip_rip_enabled,1

# VCP（待ちパターンだが信頼性高い）
ibkr_setup_vcp_enabled,1

# Momentum（最高リスク・最高リターン）
ibkr_setup_momentum_enabled,0  # ← 運用環境に応じて有効化

# 全体の優先度
ibkr_setup_mode,multi
ibkr_setup_primary_signal,orb
```

---

## 日々の監視・判断フロー

### 毎日

```
08:00 JST: ダッシュボード確認
  - 前日の取引数、WR、P&L
  - Setup 別の成績

09:30 JST (US市場開場): ライブ監視開始
  - リアルタイム notifications
  - ORB / Dip & Rip の発火状況

16:00 JST (US市場終了): 日次集計
  - Setup 別のWR計算
  - 問題がないか確認

20:00 JST: ログ分析
  - setup_details の内容確認
  - パラメータ調整の検討
```

### 週間

```
毎週月曜: 先週の結果をまとめる
  - Phase別の勝率、FP
  - 進級条件達成か判定
  - 次Phaseへの準備

毎週金曜: 来週の方針確認
  - 調整が必要なパラメータ
  - 市場環境の変化
```

---

## トラブルシューティング

### Setup が発火しない

```bash
# 1. Enable フラグ確認
grep "setup_xxx_enabled" IBKR_CONTROL.csv

# 2. ログでエラー確認
tail /home/ubuntu/trading_bot/logs/ibkr_trade_log_*.csv | grep "setup="

# 3. パラメータが厳しすぎる可能性
# 例: ORB の volume_threshold を 1.5 → 1.2 に下げる
```

### Setup は発火するが WR が悪い

```bash
# 1. サンプルサイズ確認
# < 5件なら統計的に無意味

# 2. FP が多い → 出来高フィルタを厳しく
# 例: volume_threshold を 1.5 → 2.0 に上げる

# 3. 時間帯の問題
# ORB は 9:45-10:30 ET が最良
# VCP は午後も含めて発火することがある
```

---

## ロールバック手順（問題発生時）

```bash
# 即座に問題のSetupを無効化
# 例: VCP で大負けした場合

IBKR_CONTROL.csv:
ibkr_setup_vcp_enabled,0

# VM 再起動
ssh ubuntu@161.33.26.35
sudo systemctl restart ouroboros-ibkr-bot.service

# ログ確認
tail -f ibkr_trade_log_*.csv | grep "setup="
# VCP が消えて、他のSetupのみになったことを確認
```

---

## Success Criteria（進級判定）

### Phase 1 → Phase 2

```
✅ 5営業日以上
✅ WR ≥ 40%
✅ FP ≤ 20%
✅ ダッシュボール表示OK
✅ ログ記録に誤りなし
```

### Phase 2 → Phase 3

```
✅ Phase 2 のWR ≥ 40%
✅ Phase 1 の統合WR ≥ Phase 1 単独時のWR
  (追加したSetupで全体が悪化していないか)
✅ 複合SetupのFP が許容範囲
```

### Phase 3 → Phase 4

```
✅ Phase 3 のWR ≥ 35% (待ちパターンなので若干低め許容)
✅ Phase 1-3 統合WR ≥ 40%
✅ リスク管理が良好（SL 執行率が適切）
```

### Phase 4 継続可否

```
✅ WR ≥ 40% → 継続
⚠️ 35-40% → 2週間延長、パラメータ調整
❌ < 35% → 無効化検討
```

---

## VM デプロイ確認チェックリスト

Phase 進級ごとに確認:

```
[ ] IBKR_CONTROL.csv をVMにアップロード
[ ] ibkr_bot.py は最新版（Phase X 対応）
[ ] bot を再起動
[ ] ログにエラーがない
[ ] setup=XXX が出力される
[ ] ダッシュボードで setup 別の統計が表示される
```

---

## まとめ

```
実装状態: ✅ 完了
  - Phase 1: ORB (enabled)
  - Phase 2: Dip & Rip (disabled)
  - Phase 3: VCP (disabled)
  - Phase 4: Momentum (disabled)

次のステップ:
  1. VM に最新ibkr_bot.py をデプロイ
  2. ボット再起動
  3. Phase 1 PAPER テスト開始（1-2週間）
  4. 条件達成後、Phase 2 有効化 → テスト
  5. 以降、段階的に Phase 3, 4 へ

安全性: 
  - 各Phase は独立して enable/disable 可能
  - 問題発生時は即座にロールバック可能
  - ログに setup 情報を完全記録（監視容易）
```
