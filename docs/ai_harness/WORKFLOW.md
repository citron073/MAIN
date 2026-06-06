# Ouroboros Symphony-Style Workflow

この記事の「Symphony」から取り入れるのは、自動で本番を触ることではなく、作業をセッションではなくワークアイテムとして管理する考え方です。

## 目的

- 未完了作業を `docs/ai_harness/work_items.json` に集約する。
- 各作業に目的、編集範囲、検証、証跡、rollbackを持たせる。
- Codex/人間のどちらが作業しても、同じ状態遷移と品質ゲートを通す。
- VM、本番、main実弾へ勝手に触れない。

## 状態

- `BACKLOG`: まだ着手しない候補。
- `READY`: 着手可能。依存が解消されている。
- `IN_PROGRESS`: 作業中。
- `HUMAN_REVIEW`: 実装または調査が終わり、人間確認待ち。
- `DONE`: 検証とレビューが完了。
- `BLOCKED`: 外部入力、承認、ログ不足などで止まっている。
- `ABANDONED`: 採用しないと判断した。

## ワークアイテム必須項目

- `id`: 一意なID。例: `TRADE-001`
- `title`: 短い作業名。
- `status`: 上記状態のいずれか。
- `objective`: 何を達成するか。
- `allowed_files`: 編集してよいファイル。
- `runtime_impact`: `local-only`, `widget-only`, `shadow-only`, `report-only`, `VM deploy`, `main-live`。
- `safety_gate`: `observe`, `shadow`, `paper-canary`, `main-canary`, `UI-only`, `LLM-only`, `report-only`。
- `validation`: `fast`, `trade`, `all-tests`, `manual`。
- `blocked_by`: 依存するワークアイテムID。
- `proof`: 完了時に残す証跡。
- `rollback`: 問題が出た時の戻し方。

## 実行ループ

1. `python3 tools/harness_work_items.py --show-items` でREADY作業を見る。
2. `docs/ai_harness/current_spec.md` を対象作業に合わせて `Status: READY` にする。
3. `python3 tools/harness_quality_check.py` を通す。
4. 作業する。
5. 指定された `validation` を実行する。
6. 結果、影響範囲、rollbackを残して `HUMAN_REVIEW` にする。
7. 承認後に `DONE` にする。

## 安全境界

- `main-live` と `VM deploy` は明示承認なしで実行しない。
- 外部API送信、依存追加、migration、自動commitはこのworkflowの対象外。
- トレードロジックは `observe` -> `shadow` -> `paper-canary` -> `main-canary` の順を崩さない。
- 自動化の主役は状態管理と検証であり、売買判断の自動変更ではない。
