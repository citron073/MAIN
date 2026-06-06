# Note CMS Central Orchestration

Status: READY

## Goal

- `note_cms` の記事運用を壊さずに、`MAIN` 配下の中央統括ハーネスから呼べる入口を追加する。
- 記事ごとの担当割り当てと、役割マスタを分けて管理できるようにする。
- 別システムが `MAIN` 配下の skill / agent / tool / handover を読むだけで、note CMS の運用状態と担当分担を把握できるようにする。

## Input

- `note_cms_data/articles.csv`
- `note_cms_data/settings.json`
- `note_cms_data/templates.json`
- `note_cms_data/sync_history.json`
- `note_cms_data/agents.json`
- `note_cms_data/marketing/atoms.csv`
- `note_cms_data/marketing/pipeline.csv`
- `note_cms_data/marketing/outputs.csv`
- `note_cms_data/marketing/import_history.json`
- `run_note_cms.py`
- `note_cms/*.py`

## Output

- note CMS の担当割り当て UI / API / CLI
- note CMS のMarketing UI / API
- `MAIN/.claude/skills/note-cms-orchestrator/`
- `MAIN/.claude/agents/note-cms-*.md`
- `MAIN/tools/note_cms_*.py|sh`
- `MAIN/.harness/note_cms_central_context.json`
- `MAIN/.harness/note_cms_marketing_department_context.json`
- `MAIN/tools/note_cms_healthcheck.py`
- `MAIN/docs/NOTE_CMS_MARKETING_DEPARTMENT.md`
- `MAIN/COMMANDS.md`
- `MAIN/HANDOVER.md`
- `MAIN/HANDOVER.json`
- `MAIN/docs/ai_harness/README.md`

## Constraints

- `docs/ai_harness/constraints.md` を必ず守る。
- 既存の `note_cms` 記事生成、整合性チェック、Google Sheets 同期、バックアップ、X文生成を壊さない。
- `MAIN` 側は薄い入口と資料追加を優先し、note CMS 本体ロジックを `MAIN/tools` へ移しすぎない。
- 依存追加、VM deploy、systemd 変更、秘密情報追加はしない。
- 自動hookは増やさず、明示的に呼ぶ skill / tool / launchagent wrapper だけ追加する。

## Pre-Implementation Contract

- Allowed Files: note_cms/*.py, run_note_cms.py, tests/test_note_cms.py, NOTE_CMS_README.md, NOTE_CMS_SHEET_TEMPLATE.csv, MAIN/.claude/**, MAIN/tools/*.py, MAIN/tools/*.sh, MAIN/COMMANDS.md, MAIN/HANDOVER.md, MAIN/HANDOVER.json, MAIN/AGENTS.md, MAIN/docs/*.md, MAIN/docs/ai_harness/current_spec.md, MAIN/docs/ai_harness/README.md
- Runtime Impact: local-only
- Data Contract: 記事正本は引き続き CSV。役割マスタは JSON。中央統括は読み取り用の context JSON を `MAIN/.harness/` に出す。
- Safety Gate: UI-only
- Validation: fast
- Rollback: 追加した skill / agent / tool / docs / JSON を戻し、note CMS の担当列と agent 設定を削除する。

## Acceptance Criteria

- [x] note CMS の記事ごとに `writer / checker / publisher / x` 担当を保存できる。
- [x] note CMS に役割マスタ管理画面があり、デフォルト担当を保存できる。
- [x] `run_note_cms.py` から agent 設定を表示・初期化できる。
- [x] `MAIN/tools/note_cms_central_skill.py` が central context JSON を生成できる。
- [x] note CMS の記事画面に担当ごとの完了チェックが表示される。
- [x] `Agents` 画面に担当別の処理件数が表示される。
- [x] `MAIN/tools/note_cms_healthcheck.py` で同期や担当割り当ての簡易ヘルスチェックができる。
- [x] `Home` と `Agents` から担当の未完了キューを開ける。
- [x] healthcheck に最終同期からの経過分数が出る。
- [x] 保存URL同期が24時間を超えたら healthcheck が `warn` になる。
- [x] `Home` に `自分の担当だけ固定表示` があり、次回起動時も保持される。
- [x] 保存URL同期が72時間を超えたら healthcheck が `error` になる。
- [x] `Home` 冒頭で現在の担当ビューが分かる。
- [x] 担当キューから `記事生成 / 整合性チェック / X文生成` を実行できる。
- [x] `MAIN/.claude/skills` と `MAIN/.claude/agents` に note CMS 用の入口が追加される。
- [x] `MAIN/COMMANDS.md` と `MAIN/HANDOVER.*` から note CMS 中央統括の使い方が追える。
- [x] `MAIN/tools/note_cms_healthcheck.py` は `summary` 1行要約を返す。
- [x] `Home` の担当キューで `次に押す` が強調表示される。
- [x] `Home` の `運用ヘルス` から保存URLの即時同期を実行できる。
- [x] `Home` の `運用ヘルス` から確認付きで置換同期を実行できる。
- [x] `Home` の `運用ヘルス` から置換前CSV控えを書き出せる。
- [x] `Home` の `スタートガイド` から `今日の最初の1本` を作成できる。
- [x] `Home` の `スタートガイド` から `今日の1本+記事生成` を実行できる。
- [x] `今日の1本+記事生成` はテンプレセットを選んで実行できる。
- [x] `Home` の `スタートガイド` はたたみ状態を保持できる。
- [x] 置換同期前に取り込みプレビューが表示される。
- [x] 担当キューを `すべて / 24h超 / 72h超` で絞り込める。
- [x] `Home` の担当キューで対象記事の最終更新からの経過時間が見える。
- [x] `Home` の担当キューで24時間超、72時間超の記事が段階的に強調される。
- [x] `Home` 指標に `24h超` / `72h超` の未完了キュー件数が表示される。
- [x] `Agents` 画面で `この担当をデフォルトに戻す` を実行できる。
- [x] 実務向けの運用マニュアルが `MAIN/docs/NOTE_CMS_OPERATION_MANUAL.md` にある。
- [x] PDFの1人マーケ部門構成を `note_cms_data/marketing/atoms.csv` / `pipeline.csv` / `outputs.csv` に初期化できる。
- [x] `MAIN/tools/note_cms_marketing_department.py` が marketing department context JSON を生成できる。
- [x] `MAIN/.claude/skills/note-cms-marketing-department/SKILL.md` から運用原則を追える。
- [x] central context に `marketing_department` が含まれる。
- [x] Web UI の `Marketing` 画面で URL/PDF/本文読み込み、URLリスト/PDFフォルダ一括読み込み、読み込み前プレビュー、重複スキップ、読み込み履歴、履歴からの再実行、Atom追加、Atom記事化、outputs登録、簡易Week Reviewが使える。
- [x] Web UI の `Write` 画面で、本文・URL・導線・次の操作だけに絞った執筆導線が使える。
- [x] 記事画面の `リンク候補プレビュー` と `自動整備` で、note URL抽出、過去記事タイトルの内部リンク化、関連候補の導線追加ができる。
- [x] `python3 -m unittest tests/test_note_cms.py` が成功する。
- [x] `python3 tools/harness_quality_check.py --allow-draft` が成功する。

## Out Of Scope

- note への自動投稿
- X API の新規課金や権限申請
- VM 反映や systemd deploy
- LLM による自律ルーティング
