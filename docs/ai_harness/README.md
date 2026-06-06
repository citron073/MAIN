# Ouroboros AI Harness

無料で使うための最小ハーネスです。外部APIや有料LLMを前提にせず、仕様、制約、検証、レビューをファイルとローカルコマンドで固定します。

## 基本ループ

1. `docs/ai_harness/work_items.json` から着手するワークアイテムを決める。
2. `docs/ai_harness/current_spec.md` を `Status: READY` にして、作るものと受け入れ条件を書く。
3. 実装者は `docs/ai_harness/WORKFLOW.md`、`docs/ai_harness/constraints.md`、`docs/ai_harness/ouroboros_quality_gate.md` の編集境界と評価基準を守る。
4. 実装後に `./scripts/validate.sh fast` か `./scripts/validate.sh trade` を実行する。
5. 失敗したら `./scripts/extract_failures.sh` で `.harness/failures.txt` を作り、最小修正だけ入れる。
6. `docs/ai_harness/definition-of-done.md` を満たしてから、人間レビューまたはVM反映へ進む。

## Symphony-style work items

`docs/ai_harness/WORKFLOW.md` と `docs/ai_harness/work_items.json` は、OpenAI Symphonyの考え方をOuroboros向けに縮小したものです。
外部Linearや自動Codex実行は使わず、目的、編集範囲、検証、証跡、rollbackをワークアイテムとして残します。

```bash
# 台帳の整合性とREADY作業を確認
python3 tools/harness_work_items.py --show-items

# JSONで確認
python3 tools/harness_work_items.py --print-json

# current_spec.md から新しい作業を登録
python3 tools/harness_work_items.py --add-from-spec TRADE-LOGIC-003 --status BACKLOG
```

`main-live` と `VM deploy` は、台帳に載っていても明示承認なしでは実行しません。

ローカルHTTPで開いている場合は、まず `index.html` を見ると全体の入口になります。

```bash
http://127.0.0.1:8791/
```

## Ouroboros専用ゲート

`docs/ai_harness/ouroboros_quality_gate.md` に以下をまとめています。

- 実装前契約
- shadow / observe からmainへ上げる条件
- Widget / UI評価基準
- LLM / 日次反省の評価基準

迷ったら main 実弾ではなく、shadow / observe / report-only に落としてサンプルを貯めます。

## 追加チェック

```bash
# current_spec.md と品質ゲート文書を確認。DRAFTを警告扱いにする場合:
python3 tools/harness_quality_check.py --allow-draft

# Symphony-style work item ledgerを確認:
python3 tools/harness_work_items.py --show-items

# current_spec.mdを台帳へ登録:
python3 tools/harness_work_items.py --add-from-spec HARNESS-NEW --status BACKLOG

# 既存ワークアイテムの状態更新:
python3 tools/harness_work_items.py --set-status HARNESS-NEW --status DONE

# 履歴ファイルの場所:
python3 tools/harness_work_items.py --history-path

# 実装前にREADY契約を必須にする場合:
python3 tools/harness_quality_check.py

# shadow / observe の昇格候補判定:
python3 tools/shadow_promotion_report.py

# 日次反省JSONとLLM fallback状態の確認:
python3 tools/llm_reflection_audit.py

# React / Next / Viteの構成チェック:
python3 tools/react_frontend_harness_check.py --root action_reader/frontend

# VM影響なしのローカルLLM助言:
python3 tools/local_llm_healthcheck.py
./tools/sync_vm_llm_inputs.sh
python3 tools/local_llm_trade_review.py --snapshot-dir .local_llm/vm_snapshot/latest

# healthcheck + VM snapshot + review をまとめて実行:
./tools/run_local_llm_review.sh

# specテンプレを選ぶ:
python3 tools/harness_spec_template.py --list
python3 tools/harness_spec_template.py --use widget_ui --force
```

`--force` で上書きした場合、元の `current_spec.md` は `.harness/spec_backups/` に退避されます。

specの書き始めは `docs/ai_harness/spec_templates/` を使います。
Widget変更時は `docs/ai_harness/widget_checklist.md`、VM反映時は `docs/ai_harness/deploy_precheck.md` を見ます。
React/Viteの新規UIや画面整理は `docs/ai_harness/spec_templates/react_vite.md` と `docs/ai_harness/react_frontend_structure.md` を使います。既存がNext.jsの場合は、Viteへ無理に移行せず責務分離だけ読み替えます。
ローカルLLMで売買ログを深掘りする時は `docs/ai_harness/spec_templates/local_llm_hybrid.md` を使います。VMへ書き戻さず、`.local_llm/` へsnapshotと助言レポートだけを保存します。

## VS Code

Command Palette から `Tasks: Run Task` を開き、以下を使います。

- `harness: validate fast`: core構文、JSON、Scriptable JS、主要ユニットテスト。
- `harness: validate trade`: trading / widget / reflection 周辺の追加ユニットテストも実行。
- `harness: show quality gate`: Ouroboros専用ゲートを表示。
- `harness: quality gate`: `current_spec.md` がREADY契約を満たすか確認。
- `harness: quality gate draft`: DRAFTを警告扱いで文書構成だけ確認。
- `harness: work items`: Symphony-style台帳の整合性とREADY作業を確認。
- `harness: work items json`: 台帳チェック結果をJSONで確認。
- `harness: shadow promotion report`: 直近shadowログから昇格候補を保守的に判定。
- `harness: effective config dump`: CONTROL/ai_model反映後の実効設定をローカルで確認。
- `harness: effective config dump vm snapshot`: 読み取り専用VM snapshotから実効設定を確認。
- `harness: llm reflection audit`: 日次反省JSONとLLM fallbackを確認。
- `harness: local llm vm sync`: VMログ/反省JSON/CONTROLを読み取り専用で `.local_llm/vm_snapshot/` へ取得。
- `harness: local llm healthcheck`: ローカルOllamaの到達可否と使えるモデルを確認。
- `harness: local llm review run`: healthcheck、VM snapshot取得、助言レポート生成をまとめて実行。
- `harness: local llm review`: ローカルsnapshotをOllama/ルールベースで助言レポート化。
- `harness: local llm review no-llm`: Ollamaなしでfallback助言だけを生成。
- `harness: react frontend check`: 既存React/Next/Vite UIのフォルダ責務とpackage scriptsを確認。
- `harness: spec templates`: 利用できるspecテンプレを表示。
- `harness: use spec widget`: Widget用specを `current_spec.md` へコピー。
- `harness: use spec trading`: 売買ロジック用specを `current_spec.md` へコピー。
- `harness: use spec llm reflection`: LLM反省用specを `current_spec.md` へコピー。
- `harness: use spec local llm hybrid`: ローカルLLM助言用specを `current_spec.md` へコピー。
- `harness: use spec vm deploy`: VM反映用specを `current_spec.md` へコピー。
- `harness: use spec react vite`: React/Vite用specを `current_spec.md` へコピー。
- `harness: validate`: DRAFT許容の品質ゲートを通してからtrade検証。
- `harness: validate gated`: READY必須の品質ゲートを通してからtrade検証。
- `harness: extract failures`: 直近ログから失敗箇所を `.harness/failures.txt` に抽出。

## Claude Code

このプロジェクトには `.claude/skills/` と `.claude/agents/` を置いています。Claude Codeで使う場合は、明示的に以下を呼びます。

- `/implement-harness`: 仕様と制約を読んで実装し、validateまで回す。
- `/note-cms-orchestrator`: note CMS の中央統括入口。起動、同期、役割分担、context export を扱う。
- `/fix-failed-tests`: `.harness/failures.txt` を読んで最小修正する。
- `/review-diff`: 差分を厳しくレビューする。

追加した役割別 agent:

- `note-cms-operator`
- `note-cms-editor`
- `note-cms-reviewer`
- `note-cms-sync-manager`

自動hookはあえて入れていません。秘密情報、本番VM、依存更新、deployに勝手に触れないためです。
