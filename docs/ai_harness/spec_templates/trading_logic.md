# Trading Logic Spec Template

Status: READY

## Goal

- 新しい売買ロジックまたはフィルターを shadow / observe 起点で追加する。

## Input

- 対象ログ:
- 対象設定:
- 対象時間軸:

## Output

- 追加するnoteキー:
- 追加するresult:
- 追加するレポート項目:

## Constraints

- `docs/ai_harness/constraints.md` を必ず守る。
- `docs/ai_harness/ouroboros_quality_gate.md` の `Shadow / Observe 昇格条件` を守る。
- main実弾挙動は今回変更しない。

## Pre-Implementation Contract

- Allowed Files: bot.py, tools/*.py, tests/*.py, docs/**
- Runtime Impact: shadow-only
- Data Contract: 既存CSV列と既存result意味は変更しない。追加はnoteキー中心。
- Safety Gate: observe
- Validation: trade
- Rollback: 追加設定フラグを0に戻す。main実弾には影響なし。

## Acceptance Criteria

- [ ] observeまたはshadowでログが出る。
- [ ] 既存result/CSV列/daily_report/auditを壊さない。
- [ ] TP/SL/risk stop/streak stop/drift gateの優先順位を壊さない。
- [ ] `./scripts/validate.sh trade` が成功する。

## Out Of Scope

- main-canary昇格。
- 本番 `CONTROL.csv` の自動変更。

