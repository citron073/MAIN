# Local LLM Hybrid Spec Template

Status: READY

## Goal

- VMの売買実行・通知・Widgetを止めずに、ローカルLLMで日次/直近ログを深掘りする。
- ローカルが落ちてもVMに影響しない「助言専用」レイヤーにする。

## Input

- VMから読み取り専用で取得した `logs/trade_log_*.csv`
- VMから読み取り専用で取得した `logs/instances/shadow/trade_log_*.csv`
- VMから読み取り専用で取得した `logs/instances/mr_observe/trade_log_*.csv`
- VMから読み取り専用で取得した `MAIN/daily_report_out/daily_reflection_*.json`
- VMから読み取り専用で取得した `MAIN/CONTROL.csv`
- ローカルOllama: `http://127.0.0.1:11434`

## Output

- `.local_llm/vm_snapshot/<timestamp>/`
- `.local_llm/reports/local_llm_trade_review_YYYYMMDD.json`
- `.local_llm/reports/local_llm_trade_review_YYYYMMDD.md`
- Ollama healthcheck結果

## Constraints

- `docs/ai_harness/constraints.md` を必ず守る。
- VMへ書き戻さない。
- systemd restart / deploy / CONTROL.csv更新を自動実行しない。
- LLM提案は `proposal_only` とし、observe/shadow/PAPERを優先する。
- ローカルOllamaが落ちても、ルールベースfallbackでレポートを出す。

## Pre-Implementation Contract

- Allowed Files: tools/local_llm_trade_review.py, tools/local_llm_healthcheck.py, tools/run_local_llm_review.sh, tools/sync_vm_llm_inputs.sh, tools/llm_provider.py, tests/*.py, scripts/validate.sh, .vscode/tasks.json, docs/**, COMMANDS_QUICK.md, AGENTS.md, .gitignore
- Runtime Impact: local-only
- Data Contract: 既存CSV列、result定義、daily reflection JSONの既存キーを壊さない。
- Safety Gate: LLM-only
- Validation: trade
- Rollback: 追加ツール/タスク/ドキュメントを戻す。VM側変更は存在しない。

## Acceptance Criteria

- [ ] VMからログを読み取り専用でローカルsnapshotへ取得できる。
- [ ] ローカルLLMが停止していてもレポート生成が失敗しない。
- [ ] Ollamaの到達可否と使用モデルをhealthcheckできる。
- [ ] VM同期から助言レポート生成まで1コマンドで実行できる。
- [ ] 出力JSONに `writes_vm=false`, `writes_control=false`, `proposal_only=true` が入る。
- [ ] shadow/MR/time-block/日次反省をまとめて、次の安全アクションを出せる。
- [ ] `./scripts/validate.sh trade` が成功する。

## Out Of Scope

- VMの自動deploy。
- systemd restart。
- LLMによる本番 `CONTROL.csv` 自動変更。
- LIVE/main実弾の自動昇格。
