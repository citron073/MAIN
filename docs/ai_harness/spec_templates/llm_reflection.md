# LLM Reflection Spec Template

Status: READY

## Goal

- 日次反省/LLM補助を、無料またはローカル優先で強化する。

## Input

- 日次ログ:
- shadowログ:
- drift/weekly情報:
- LLMモード: off / auto / ollama / openai

## Output

- 反省JSON:
- 通知文:
- Widget短縮表示:

## Constraints

- `docs/ai_harness/constraints.md` を必ず守る。
- `docs/ai_harness/ouroboros_quality_gate.md` の `LLM / 日次反省 評価基準` を守る。
- LLMが落ちてもルールベースfallbackで動かす。

## Pre-Implementation Contract

- Allowed Files: tools/trade_event_notifier.py, tools/llm_provider.py, tools/apply_daily_reflection.py, tools/*.py, tests/*.py, docs/**
- Runtime Impact: report-only
- Data Contract: reflection JSONに追加する場合は既存キーを壊さない。
- Safety Gate: LLM-only
- Validation: trade
- Rollback: LLMモードをoffまたはauto fallbackに戻す。

## Acceptance Criteria

- [ ] LLMなしでも反省レポートが出る。
- [ ] 勝因/敗因/翌日の推奨設定/注意点が短く構造化される。
- [ ] main実弾設定をLLM単独で変更しない。
- [ ] 二重送信しない既存ガードを壊さない。
- [ ] `./scripts/validate.sh trade` が成功する。

## Out Of Scope

- LLMによる本番 `CONTROL.csv` 自動変更。
- 有料API必須化。

