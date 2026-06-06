# Ouroboros Agent Guide

このリポジトリでCodex/Claude CodeなどのAI作業をする時の共通ルールです。

## First Read

- `docs/ai_harness/current_spec.md`
- `docs/ai_harness/constraints.md`
- `docs/ai_harness/ouroboros_quality_gate.md`
- `docs/ai_harness/definition-of-done.md`
- `docs/ai_harness/review_rubric.md`

## Rules

- `current_spec.md` が `Status: READY` でない場合、実装は始めない。
- main実弾挙動の変更は、shadow / observe / report-onlyを先に通す。
- 既存の `result` 意味、CSV列、daily report / audit の集計定義を壊さない。
- 秘密情報、トークン、APIキーを表示・保存・最終回答に含めない。
- VM deploy、systemd再起動、`CONTROL.csv` の本番値変更は明示確認してから行う。
- Widget変更は small / medium / large と通信NG表示を考慮する。
- LLM/日次反省はfallback必須。LLM単独でmain実弾設定を変えない。
- ローカルLLMは助言専用。VM snapshotを読み、`.local_llm/` に出力するだけで、VMへ書き戻さない。
- React/Vite UI作業は `docs/ai_harness/react_frontend_structure.md` を読み、既存Next.jsを無確認でViteへ移行しない。
- `note_cms` の中央統括連携は local-only に保ち、`note_cms/` を正本、`MAIN/tools` は薄い入口とcontext exportに留める。
- 売買ロジック、noteキー、stateキー、runner間隔を変えたら `docs/OUROBOROS_TRADING_SPEC_TABLE.md` / `HANDOVER.md` / `HANDOVER.json` / `COMMANDS_QUICK.md` を同時更新する。

## Validation

```bash
./scripts/validate.sh fast
./scripts/validate.sh trade
```

失敗時:

```bash
./scripts/extract_failures.sh
```

品質ゲート確認:

```bash
python3 tools/harness_quality_check.py --allow-draft
python3 tools/shadow_promotion_report.py
python3 tools/llm_reflection_audit.py
python3 tools/local_llm_healthcheck.py
./tools/sync_vm_llm_inputs.sh
python3 tools/local_llm_trade_review.py --snapshot-dir .local_llm/vm_snapshot/latest --llm-mode off
```
