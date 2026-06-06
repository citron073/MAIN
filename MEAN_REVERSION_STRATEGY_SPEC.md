# Mean Reversion Strategy Spec

最終更新: 2026-04-08 JST

## 1. 目的

平均回帰（Mean Reversion）戦略を、既存の Ouroboros Bot に安全に追加するための実装指針。

この戦略は、すぐに勝たせるためのものではなく、

- ログ精度
- 再現性
- 後分析のしやすさ

を優先して段階導入する。

## 2. 最重要制約

- 既存 `result` 定義を壊さない
- 既存ログ列を削除・変更しない
- `daily_report.py` / `audit.py` / widget 集計を壊さない
- 全置換は禁止、差分追加のみ
- 初期は `OBSERVE` 中心で、いきなり live/paper に入れない

## 3. 導入方針

### Phase 1

- `OBSERVE_MR`
- `OBSERVE_MR_FILTER_NG`
- `OBSERVE_MR_TRIGGER`

のみ追加

この段階では新規建玉しない。

### Phase 2

- `mr_setup_rank=A` のみ `PAPER` 検証
- 既存戦略とは別レイヤーで実行

### Phase 3

- score / regime / level type / MAE / MFE を見て最適化

## 4. 戦略の本質

平均回帰は、トレンド追従ではなく「伸び切った動きの失速」を狙う。

前提条件:

- 急なスパイク
- 出来高が増えていない、または減速していること
- 非トレンド環境
- 左側構造が維持されていること
- レベル回帰クローズが出ていること

## 5. 実装レイヤー

以下を既存ロジックに差分追加する。

1. 環境判定
2. レベル抽出
3. トリガー判定
4. リスク計算
5. スコアリング
6. ログ出力

## 6. 実行フロー

1. データ取得
2. MA 更新
3. レベル抽出
4. スパイク判定
5. 出来高判定
6. MA 環境判定
7. 左側構造判定
8. スコア算出
9. トリガー判定
10. リスク計算
11. OBSERVE / PAPER
12. ログ出力

## 7. フィルター仕様

### 7.1 Spike

出力:

- `mr_is_spike`
- `mr_spike_score`

候補指標:

- 到達本数
- 到達距離
- 傾き

### 7.2 Volume

現時点では未確定。
安定して取得できない場合は skip 可能な構造にする。

出力:

- `mr_volume_state`
- `mr_volume_score`

### 7.3 MA 環境

出力:

- `mr_ma_cross_count`
- `mr_ma_slope`
- `mr_market_regime` (`range` / `trend`)
- `mr_ma_score`

狙い:

- 非トレンド環境の抽出
- クロス回数の多さ
- 傾きの弱さ

### 7.4 左側構造

出力:

- `mr_left_structure`
- `mr_structure_score`

候補指標:

- rejection 回数
- breakout 失敗回数

## 8. レベル仕様

抽出対象:

- 直近高値 / 安値
- 複数回反発した価格帯

出力:

- `mr_level_price`
- `mr_level_type` (`support` / `resistance`)
- `mr_level_touch_count`
- `mr_level_age_min`

## 9. エントリー仕様

### 9.1 ショート

- resistance へスパイク
- 一度上抜け
- その後、レベル下でクローズ

### 9.2 ロング

- support へスパイク
- 一度下抜け
- その後、レベル上でクローズ

出力:

- `mr_reclaim_close`
- `mr_trigger_price`

## 10. リスク管理

### 10.1 SL

- swing high / low 基準
- 最低 1.0% 以上離す

出力:

- `mr_stop_price`
- `mr_stop_distance_pct`

### 10.2 TP

- 1R 固定

出力:

- `mr_tp_price`
- `mr_tp_r=1.0`

### 10.3 ロット

- `A -> 1.0`
- `B -> 0.5`
- `C -> 0`

## 11. スコアリング

構成:

- spike
- volume
- MA
- structure

初期は 4 点満点でよい。

判定:

- `4点 -> A`
- `3点 -> B`
- `2点以下 -> skip`

出力:

- `mr_score_total`
- `mr_setup_rank`

## 12. ログ方針

既存列は変えない。
追加情報は `note` に埋め込む。

例:

```text
strategy=MR
mr_score=4
mr_rank=A
mr_spike=1
mr_ma=1
mr_structure=1
mr_reclaim=1
mr_stop_pct=1.2
mr_tp_r=1.0
```

## 13. result 方針

追加は最小限。

- `OBSERVE_MR`
- `OBSERVE_MR_FILTER_NG`
- `OBSERVE_MR_TRIGGER`

既存 result 群の意味は変えない。

## 14. レポート拡張

将来追加したい集計:

- MR 候補数
- rank 別件数
- rank 別勝率
- MAE / MFE
- `mr_level_type` 別成績

## 15. audit / dashboard 方針

### audit

- `pos_id` 整合性
- score と結果の相関
- `mr_stop_distance_pct >= 1.0` の検証

### dashboard

表示したいもの:

- `strategy=MR`
- rank
- regime
- score 内訳
- MAE / MFE
- stop 距離

## 16. Ouroboros 向けの安全な実装順

1. `bot.py` に MR 用の観測関数を追加
2. `OBSERVE_MR*` を note 付きで出す
3. `daily_report.py` / `audit.py` が既存のままでも壊れないことを確認
4. MR 専用の note parse を追加
5. `Aランクのみ PAPER`
6. shadow で十分サンプルが取れたら main 昇格判定

## 17. 今の判断

この仕様は採用価値あり。
ただし、最初に入れるべきなのは「売買ロジック」ではなく、

- note へ落ちる観測層
- filter / rank / trigger のログ精度
- report / audit / dashboard へ安全に乗る構造

の 3 点。

つまり最初のゴールは、

`勝つこと` ではなく `MR候補を壊さず計測できること`

に置く。
