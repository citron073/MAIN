# Widget UI Spec Template

Status: READY

## Goal

- Scriptable Widgetの表示を、対象サイズで見切れないように改善する。

## Input

- 対象サイズ: small / medium / large
- 対象スクショ:
- 追加または優先したい情報:

## Output

- 更新対象Scriptableファイル:
- 表示バージョンまたは見分け用ラベル:

## Constraints

- `docs/ai_harness/constraints.md` を必ず守る。
- `docs/ai_harness/ouroboros_quality_gate.md` の `Widget / UI 評価基準` を守る。
- JSON payloadの欠損や古いサーバーでも壊れない。

## Pre-Implementation Contract

- Allowed Files: widget/scriptable/*.js, tools/widget_status.py, tests/*.py, docs/**
- Runtime Impact: widget-only
- Data Contract: 既存payloadキーは壊さない。追加キーは欠損時fallbackを持つ。
- Safety Gate: UI-only
- Validation: trade
- Rollback: 直前のScriptable exportを再publishする。

## Acceptance Criteria

- [ ] mediumで上下左右が見切れない。
- [ ] small/largeでも最低限壊れない。
- [ ] 通信NG時に短いエラー表示が出る。
- [ ] `node --check widget/scriptable/OuroborosWidget.local.js` が成功する。
- [ ] `./scripts/validate.sh trade` が成功する。

## Out Of Scope

- 売買ロジック変更。
- VM設定変更。

