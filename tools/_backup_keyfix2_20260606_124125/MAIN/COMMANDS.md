# Ouroboros 運用コマンド一覧（詳細版）

このファイルは **2026-05-16 時点（dashboard v1.1.8 / YT Tool v1.99.86）** の運用手順です。  
目的は「迷わず、安全に、再現可能に運用する」ことです。

## 使い分け
- まず見る: `MAIN/COMMANDS_QUICK.md`（毎朝5分チェック）
- 詳細確認: この `MAIN/COMMANDS.md`
- 引き継ぎ（別トーク再開時）: `MAIN/HANDOVER.md`（人向け） / `MAIN/HANDOVER.json`（機械向け）
- 簡易ステータス表示: `MAIN/WIDGETS.md`

## 0. まず移動
```bash
cd ~/trading_bot/trading_bot/MAIN
```

## 0-H. 無料AIハーネス（仕様→実装→検証→レビュー）
```bash
cd ~/trading_bot/trading_bot/MAIN

# まず仕様を READY にしてから実装する
open docs/ai_harness/current_spec.md

# Ouroboros専用の判断基準: 実装前契約 / shadow昇格 / UI / LLM反省
open docs/ai_harness/ouroboros_quality_gate.md

# DRAFT中でも文書構成をチェック
python3 tools/harness_quality_check.py --allow-draft

# Symphony-styleの作業台帳を確認
python3 tools/harness_work_items.py --show-items

# current_spec.mdを作業台帳へ登録
python3 tools/harness_work_items.py --add-from-spec HARNESS-NEW --status BACKLOG

# 作業台帳の状態だけ更新
python3 tools/harness_work_items.py --set-status HARNESS-NEW --status DONE

# main-live / VM deploy など明示承認済みのDONE化
python3 tools/harness_work_items.py --set-status HARNESS-NEW --status DONE --force

# 作業台帳の履歴ファイルを確認
python3 tools/harness_work_items.py --history-path

# specテンプレを選ぶ
python3 tools/harness_spec_template.py --list
python3 tools/harness_spec_template.py --use widget_ui --force

# 実装前に READY 契約を必須チェック
python3 tools/harness_quality_check.py

# shadowをmainへ上げられるか保守的に確認
python3 tools/shadow_promotion_report.py
python3 tools/shadow_promotion_report.py --lookback-days 7 --min-mr-rank-a 3

# CONTROL/ai_model反映後の実効設定だけ確認（書込なし）
python3 tools/effective_config_dump.py
python3 tools/effective_config_dump.py --snapshot-dir .local_llm/vm_snapshot/latest

# 日次反省/LLM fallbackの出力確認
python3 tools/llm_reflection_audit.py

# 軽い検証: core構文 + widget JS + 主要テスト
./scripts/validate.sh fast

# trading / widget / notifier / reflection 周辺まで見る検証
./scripts/validate.sh trade

# YT Tool の配布前ゲート: version / docs / dist / QA harness 同梱を無料チェック
cd ~/trading_bot/trading_bot/MAIN
python3 tools/package_yt_tool_bundle.py

# 失敗時だけ、直近ログから要点を抽出
./scripts/extract_failures.sh
```

補足:
- specテンプレは `docs/ai_harness/spec_templates/` にあります。
- Symphony-styleの最小運用は `docs/ai_harness/WORKFLOW.md` と `docs/ai_harness/work_items.json` で管理します。外部Linearや自動VM操作は使いません。
- ローカルHTTPで開く場合の入口は `http://127.0.0.1:8791/` です。
- Widget変更時は `docs/ai_harness/widget_checklist.md`、VM反映時は `docs/ai_harness/deploy_precheck.md` を確認します。
- VS Code では `Tasks: Run Task` から `harness: validate fast` / `harness: validate trade` / `harness: validate` / `harness: validate gated` / `harness: quality gate` / `harness: work items` / `harness: shadow promotion report` / `harness: effective config dump` / `harness: llm reflection audit` を実行できます。
- Claude Code では `.claude/skills/implement-harness` / `fix-failed-tests` / `review-diff` と `.claude/agents/qa-reviewer.md` を追加済みです。
- 自動hookは未設定です。秘密情報、本番VM、deployに勝手に触れないよう、最初は手動実行にしています。

## 0-I. note CMS 中央統括
```bash
cd ~/trading_bot/trading_bot/MAIN

# ローカルWeb UI起動
./tools/run_note_cms_web.sh

# 保存済みGoogle Sheets URLから差分同期
./tools/sync_note_cms_saved_google.sh

# 保存済みGoogle Sheets URLから置換同期
./tools/sync_note_cms_saved_google.sh replace

# 中央統括用contextを書き出し
python3 tools/note_cms_central_skill.py --stdout

# 1人マーケ部門用CSVを初期化してcontextを書き出し
cd ~/trading_bot/trading_bot
python3 run_note_cms.py --marketing-init
python3 run_note_cms.py --marketing-context
cd ~/trading_bot/trading_bot/MAIN
python3 tools/note_cms_marketing_department.py --stdout

# note CMS の簡易ヘルスチェック
python3 tools/note_cms_healthcheck.py
python3 tools/note_cms_healthcheck.py --json

# 実務向けの運用マニュアルを開く
open docs/NOTE_CMS_OPERATION_MANUAL.md
open docs/NOTE_CMS_MARKETING_DEPARTMENT.md

# 定期同期のLaunchAgentを入れる
./tools/install_note_cms_sync_launchagent.sh 1800

# 定期同期のLaunchAgentを外す
./tools/uninstall_note_cms_sync_launchagent.sh
```

補足:
- `note_cms_healthcheck.py` は最終同期からの経過分数も表示します。
- `note_cms_healthcheck.py` は `summary=...` の1行要約も表示します。
- `note_cms_marketing_department.py` はPDFの1人マーケ部門構成を `atoms / pipeline / outputs` の共有CSVとして初期化します。
- 共有CSVは `note_cms_data/marketing/` に置き、note投稿は引き続き手動です。
- Web UI の `Marketing` 画面から URL/PDF/本文の読み込み、URLリスト/PDFフォルダ一括読み込み、Atom追加、Atom記事化、公開結果登録、簡易Week Reviewを使えます。
- Web UI の `Write` 画面は、本文・URL・導線・次の操作だけに絞ったかんたん執筆画面です。
- 記事画面の `リンク候補プレビュー` で、完全一致リンクと関連過去記事候補を確認できます。
- 記事画面の `自動整備` で、貼り付け本文からnote URLを拾い、過去記事タイトルの内部リンク化と関連候補の導線追加ができます。
- `読み込み前プレビュー` で新規、重複、エラー見込みを確認できます。
- 読み込み済みのURL、PDFパス、本文ハッシュは重複登録をスキップします。
- 読み込み実行履歴は `note_cms_data/marketing/import_history.json` とWeb UIの `Import History` に残ります。
- `Import History` から `失敗だけ再実行` と `重複以外を再実行` を使えます。再実行結果も別履歴として残ります。
- 保存URL同期が24時間を超えて古い場合は `warn` になります。
- 保存URL同期が72時間を超えて古い場合は `error` になります。
- `Home` の `運用ヘルス` から `今すぐ同期` を押せます。
- `Home` の `運用ヘルス` から確認付きで `置換同期` も押せます。
- `Home` の `運用ヘルス` から `置換前CSV控え` も書き出せます。
- `置換同期` は取り込みプレビューを表示してから確認します。
- `Home` の `スタートガイド` はたたみ状態を保持します。
- `Home` の `スタートガイド` から `今日の最初の1本` を作れます。
- `Home` の `スタートガイド` からテンプレを選んで `今日の1本+記事生成` も実行できます。
- `Agents` 画面の `未完了を見る` から、その担当の未完了記事だけをすぐ開けます。
- `Home` の担当キューから `記事生成 / 整合性チェック / X文生成` をそのまま実行できます。
- `Home` の担当キューは `すべて / 24h超 / 72h超` で絞り込めます。
- `Home` の担当キューでは `次に押す` が強調表示されます。
- `Home` の担当キューでは対象記事の最終更新からの経過時間も見えます。
- `Home` の担当キューでは24時間超、72時間超の記事を段階的に強調します。
- `Home` 指標には `24h超` / `72h超` の未完了キュー件数も出ます。
- `Home` の `自分の担当だけ固定表示` は次回起動時も維持されます。
- `Agents` 画面の `この担当をデフォルトに戻す` で、役割カードの担当をそのままデフォルトへ戻せます。

役割:
- `note-cms-operator`: 起動、バックアップ、導線
- `note-cms-editor`: 下書き、テンプレ、最終稿、X文
- `note-cms-reviewer`: 整合性チェック、確認、公開準備
- `note-cms-sync-manager`: Google Sheets 同期、定期実行、履歴確認

中央統括skill:
- `.claude/skills/note-cms-orchestrator/SKILL.md`
- `.claude/skills/note-cms-marketing-department/SKILL.md`

## 0-1. バージョン確認
```bash
cd ~/trading_bot/trading_bot/MAIN
python3 yt_tool.py --version
python3 - <<'PY'
import json
import pathlib
import re
import bot

root = pathlib.Path(".")
dashboard = re.search(r'APP_VERSION = "([^"]+)"', (root / "dashboard.py").read_text(encoding="utf-8")).group(1)
widget = re.search(r'WIDGET_SERVER_VERSION = "([^"]+)"', (root / "tools/widget_status.py").read_text(encoding="utf-8")).group(1)
handover = json.load(open(root / "HANDOVER.json", encoding="utf-8"))

print("bot.version =", bot.OUROBOROS_BOT_VERSION)
print("feature.schema =", bot.OUROBOROS_FEATURE_SCHEMA_VERSION)
print("dashboard.version =", dashboard)
print("widget.version =", widget)
print("mr_observe.phase =", "phase1-observe-only")
print("handover.updated_at_jst =", handover["meta"]["updated_at_jst"])
print("handover.versions =", handover["versions"])
PY

# bot.py / HANDOVER / SPEC表 / テストのバージョン整合チェック
python3 tools/version_consistency_check.py

# Daily Opsにも同じ整合性チェック結果を保存して、iPhoneダッシュボードに表示
python3 tools/daily_ops_check.py --timeout-sec 15

# Daily OpsでIBKRが「smoke再実行」なら、IB Gateway Paper起動後に読み取り専用で確認
# ダッシュボードの「IB Gateway」と「IBGW/TWS 7497」がOKになってから実行
python3 test_ibkr_connection.py --stocks AAPL,MSFT,NVDA,TSLA,QQQ,SPY --fx USDJPY

# IB Gatewayの読み取り専用watch（dry-runで通知文だけ確認）
python3 tools/ibkr_gateway_watch.py --dry-run

# IB Gateway watchを5分ごとに自動化（異常/復旧だけntfy、注文は出さない）
./tools/install_ibkr_gateway_watch_launchagent.sh
```

注意:
- MacBookを閉じて通常スリープに入ると、LaunchAgent / IB Gateway / watch は止まります。
- VM上のbotやダッシュボード本体はMacを閉じても影響しません。Mac側のIB Gateway監視・株価読み取りだけが止まります。
- 閉じたまま継続したい場合は、電源接続 + 外部ディスプレイ等のクラムシェル運用、またはMacをスリープさせない運用が必要です。

VM側へIB Gatewayを寄せる準備チェック:
```bash
# ローカル計画だけ出す（VM接続なし）
python3 tools/vm_ibkr_gateway_readiness.py

# VMを読み取り専用で確認（install/start/port公開なし）
python3 tools/vm_ibkr_gateway_readiness.py \
  --host 161.33.26.35 \
  --key /Users/tani/Downloads/ssh-key-2026-03-04-4.key

# VM側IB Gatewayへは公開ポートではなくSSHトンネルでつなぐ
./tools/open_vm_ibkr_tunnel.sh \
  --host 161.33.26.35 \
  --key /Users/tani/Downloads/ssh-key-2026-03-04-4.key

# 別ターミナルで読み取り専用smoke
python3 test_ibkr_connection.py --host 127.0.0.1 --port 17497 --client-id 11 --stocks AAPL,MSFT,NVDA,TSLA,QQQ,SPY --fx USDJPY
```

## 0-U. Unified Dashboard
```bash
cd ~/trading_bot/trading_bot/MAIN

# file:// ではなくローカルHTTPで開く
./tools/start_unified_dashboard.sh

# iPhone / LAN / Tailscale から開く
./tools/start_unified_dashboard.sh --public

# iPhone / Tailscale 限定で開く（おすすめ）
./tools/start_unified_dashboard.sh --tailscale --port 8793

# Mac起動時にTailscale用ダッシュボードを自動起動
./tools/install_unified_dashboard_launchagent.sh --mode tailscale --port 8793

# URL
# http://127.0.0.1:8792/tools/unified_dashboard.html
```

補足:
- `file:///.../tools/unified_dashboard.html` 直開きは非推奨です。ブラウザの `fetch()` 制限で読み込みが止まることがあります。
- 起動スクリプトはキャッシュ事故を避けるため、自動で `?v=YYYYmmdd_HHMMSS` 付きURLを表示します。
- `--public` は `0.0.0.0` で待ち受け、`LAN=` と `Tailscale=` のURLを表示します。外出先のiPhoneはTailscale URLを使うのが安全です。
- `--tailscale` はTailscaleの `100.x` アドレスだけで待ち受けます。外出先iPhone用途ではこちらが安全です。
- LaunchAgentを外す場合は `./tools/uninstall_unified_dashboard_launchagent.sh` を使います。
- 画面の `Health` には `Dashboard Build / Validate` が出ます。古い画面やDONE前検証状態の確認に使います。
- 設定パネルが触れない場合、画面内の `接続設定ショートカット` から Widget URL と Bearer Token を保存できます。
- Bearer Token はブラウザの localStorage に保存されます。コードやログには保存しません。

売買ロジックの実装表:
- `docs/OUROBOROS_TRADING_SPEC_TABLE.md`

チャート/OHLC確認:
```bash
python3 - <<'PY'
import json
from pathlib import Path

for name in ["state_shadow.json", "state_mr_observe.json", "state.json"]:
    path = Path(name)
    if not path.exists():
        print(name, "missing")
        continue
    state = json.loads(path.read_text(encoding="utf-8"))
    cur = state.get("_ohlc_current") or {}
    hist = state.get("ohlc_history") or []
    print(name, "cur_start=", cur.get("start"), "ticks=", cur.get("ticks"), "hist=", len(hist))
PY
```

A/B/C局面（Market Phase）:
- `phase=A`: 下落局面。SELL文脈
- `phase=B`: 横ばい局面。避ける候補
- `phase=C`: 上昇局面。BUY文脈
- `up_break=1`: 直前OHLC足の高値を上抜け
- `down_break=1`: 直前OHLC足の安値を下抜け
- `phase_momentum=UP_BREAK/DOWN_BREAK`: 局面方向とブレイク方向が一致

安全運用:
```text
market_phase_enabled=1
market_phase_block_b_enabled=0
ai_use_market_phase=1
trade_notify_market_phase_enabled=1
```

shadowでB局面を強制回避する検証:
```text
market_phase_block_b_enabled=1
```

shadowでTP寸前戻しを早逃げ検証:
```text
near_tp_giveback_exit_enabled=1
near_tp_giveback_exit_only_paper=1
near_tp_giveback_exit_trigger_ratio=0.85
near_tp_giveback_exit_min_giveback_pct=0.04
near_tp_giveback_exit_max_current_fav_pct=0.06
```

相場流 Phase 1:
- `aiba_cross=KUCHIBASHI`: 5MAが20MAを上抜け、両方上向き
- `aiba_cross=REV_KUCHIBASHI`: 5MAが20MAを下抜け、両方下向き
- `aiba_ppp=PPP/REV_PPP`: 5/20/60MAの順行・逆行並び
- `aiba_9=1`: 同方向MA順序が警戒本数に到達。単独exitは禁止
- `aiba_try_fail=1`: 高値未更新 + 終値下落が連続。BUY逆風の観測タグ

安全運用:
```text
aiba_style_enabled=1
aiba_style_ai_enabled=0
aiba_ma_short_n=5
aiba_ma_mid_n=20
aiba_ma_long_n=60
aiba_nine_rule_alert_n=9
aiba_try_fail_min_count=2
```

## 0-A. ActionReader（1コマンド起動）
```bash
cd ~/trading_bot/trading_bot/MAIN/action_reader
./run_local.sh
```

開くページ:
- `http://127.0.0.1:3000/books/new`
- `http://127.0.0.1:3000/manual`
- `http://127.0.0.1:3000/specs`

停止:
```bash
cd ~/trading_bot/trading_bot/MAIN/action_reader
./stop_local.sh
```

## 0-0. 動画自動編集（字幕/不要カット/見どころ強調/サムネ/縦横書き出し）
YT Tool VER:
```bash
python3 yt_tool.py --version
```

環境診断:
```bash
python3 yt_tool.py --doctor
python3 yt_tool_desktop.py --doctor
```

ローカルLLM補助の例:
```bash
# Ollama を使う場合
python3 yt_tool.py \
  --input /path/to/video.mp4 \
  --output-dir ./yt_tool_out \
  --base-name my_video \
  --llm-mode ollama \
  --llm-model qwen2.5:1.5b \
  --llm-features highlights,metadata,chapters,subtitle_polish \
  --subtitle-polish-strength medium \
  --platform-profile shorts

# LM Studio 等の OpenAI互換API を使う場合
python3 yt_tool.py \
  --input /path/to/video.mp4 \
  --output-dir ./yt_tool_out \
  --base-name my_video \
  --llm-mode openai_compat \
  --llm-base-url http://127.0.0.1:1234/v1 \
  --llm-model local-model \
  --llm-features highlights,metadata,chapters
```

```bash
# 標準実行（16:9 + 9:16 + 1:1 まで自動出力）
python3 yt_tool.py \
  --input /path/to/video.mp4 \
  --output-dir ./yt_tool_out \
  --base-name my_video

# ブラウザUI（Launch Pad / Motion Studio / Run Archive / Library Atlas）
# 大容量対応（既定: 10,000MB）
YT_TOOL_MAX_UPLOAD_MB=10000 YT_TOOL_MAX_MESSAGE_MB=1000 ./tools/start_yt_tool_app.sh

# UIの「編集スタジオ」
# 元動画ライブラリや既存 run の Final / manual 動画から、
# trim / zoom / pan / video fade / audio fade に加えて、
# 短い text overlay と fade_in / fade_out / fade_in_out / slide_up を non-destructive に別動画として書き出せる
# Visual Timeline で clip の位置/長さを見ながら、Clip Inspector で開始/終了/モーション/テキスト/フェードを直接編集できる
# Batch Actions で複数 clip をまとめて選び、motion / text overlay / numbered text overlay / text animation / text position / text size/color / text start/end / audio gain / audio duck / BGM layer / BGM gain / video/audio fade を一括反映できる
# 複数 clip への 使用ON/OFF / useトグル / 複製 / 削除 も Batch Actions からまとめて実行できる
# 左詰め / 等間隔化 / gap 挿入 で、選択した複数 clip のテンポをまとめて整えられる
# playhead 基準で先頭をそろえる / head から左詰め / V/Aフェード ±0.05 / Vol ±1dB / Duck ±1dB も Batch Actions からまとめて触れる
# BGM ±1dB と `BGM+Duck preset` も Batch Actions からまとめて触れ、Studio BGM が選ばれていれば一発で BGM layer と duck を入れられる
# `Slow 0.85x / Boost 1.15x / Punch 1.25x / Speed反映` で、複数 clip の speed をまとめて変えられる
# `BGMフェード ±0.05` と `BGMフェード上書き` で、選択 clip の BGM layer の入り/抜けもまとめて整えられる
# Clip Inspector と data editor からは text overlay の表示開始/終了秒、clip 単位の BGM layer / BGM音量(dB) も直接編集できる
# `文字IN=head / 文字OUT=head / 文字全体` で、playhead 基準の text overlay 表示区間を batch / Clip Inspector の両方から即セットできる
# `playhead で分割+後半Text` で、head 位置で clip を切りながら後半 clip にだけテキストを即セットできる
# `選択を head で分割 / 選択を分割+後半Text` で、playhead をまたぐ複数 clip をまとめて split できる
# `選択IN=head / 選択OUT=head / 選択をI/O範囲へ` で、複数 clip の基準位置を playhead と I/O から一気に揃えられる
# `Text/BGM preset` で、文字スタイル / 表示秒 / duck / BGM layer / fade を名前付きで保存して再適用できる
# 現在の案件名に一致する Text/BGM preset は上段候補として出る
# `Batch Export preset` で、Studio BGM / BGM+Duck preset / Speed / 選択中 Text/BGM preset をまとめて保存して再適用できる
# `出力順` を直接変えると、source の時刻順ではなくその順番で clip を連結して書き出せる

# 実行履歴から字幕プレビュー / 手動微調整
# 字幕行・強調区間に加えて keep timeline を編集し、
# manual_tune.json / manual_subtitles.srt / manual_subtitles.ass / manual_timeline.mp4 / manual_final.mp4 を別保存
# 字幕行ごとに 色(HEX) / サイズ / 最大行数 / 強調 も指定でき、manual ASS と manual final だけに反映
# 同時発話の焼き込み字幕は ASS の段積みで上下に逃がし、重なりを減らす
# `--subtitle-overlap-layout speaker_fixed` で話者固定段も使える
# Run Archive の run 詳細では、`動的段積み` で書き出された run に警告ラベルが出る

# サイドバーの「テンプレート / 用語辞書」
# Shorts用や対談用の設定テンプレを保存し、固有名詞辞書は実行時に字幕補正へ自動マージ
# `方言リファレンス` で宮崎弁を選ぶと、代表語彙と表記ゆれ補正も別レイヤーで自動マージ
# `個人用の方言補強メモ / 置換` に、その人特有の口癖や聞き間違いやすい語を追加できる
# 候補フレーズ / 候補置換 は、入っている補強語をもとに宮崎弁らしい語尾や表記ゆれ補正を提案する
# 追加した回数が多い候補ほど上に出るので、使うほどあなた向けの順番に育つ
# `実字幕から拾った候補` は recent run の字幕から実際に出た方言語を拾い、例文を見ながら補強欄へ戻せる
# 案件名ごとに方言補強が自動保存される。さらに `投稿先` を入れると案件/投稿先ごとに方言辞書が枝分かれする
# LLM自動判定をONにすると observed 候補から案件/投稿先別の自動方言辞書も育つ。投稿先別の辞書が無い時は案件共通へ安全にフォールバックする

# 実行履歴 / 整理ライブラリの「完成前チェック」
# 完成動画・字幕・見どころ・タイトル・タグ・サムネ候補を自動診断し、Quality Check JSON を出力

# 実行履歴 / 整理ライブラリの「レビュー共有パッケージ」
# 完成動画・字幕・サムネ候補・品質診断・修正メモをまとめた review_package と ZIP を生成
# raw サムネに加えて、文字載せ済みの composed thumbnail も同梱される

# サイドバーの「素材ライブラリ」
# BGM / SE / Font / Thumbnail Template をローカル保存
# BGM / SE は保存済み素材からそのまま適用できる
# Font / Template はサムネ自動合成へそのまま適用できる

# 実行履歴 / 整理ライブラリの「A/B比較と採用管理」
# タイトル候補・説明文候補・サムネ候補・版候補を比較して、採用した内容を固定保存
# 完成動画A/B を ON にすると、見どころを冒頭へ移した Hook Intro 版や Hook Pack 版も版候補に追加される
# 採用内容は投稿先ごとのテンプレートにも自動反映され、次回の初期値になる
# 投稿文テンプレートも同時に自動生成され、文体プリセット（標準/フック強め/簡潔/CTA強め）を選べる
# YouTube / Shorts / TikTok / Reels 向けの投稿文を同時生成して、タブ表示とダウンロードができる
# 同じ投稿先で使うほど、文体の採用回数と同時生成先が学習されて次回の既定値へ反映される
# タイトル候補 / 説明文候補の順番も、投稿先ごとの採用傾向で learned score 付きに寄る
# サムネ候補 / 版候補の順番も、投稿先ごとの採用傾向で learned score 付きに寄る
# 「推奨候補の承認フロー」から、承認した項目だけ現在の選択へ一括反映できる
# 推奨候補ごとに「理由: 過去採用回数 / キーワード傾向 / 平均文字数 / 版トークン一致」も表示される
# 反映後は「最終承認ビュー」で、変わった項目だけを 変更前 / 変更後 で確認してから保存できる
# 保存すると承認した差分と理由が「承認履歴」に残り、review package にも approval_history.json が同梱される
# 承認履歴は次回の候補並びと推奨理由にも反映され、「承認学習: ...件」で効き方を確認できる
# 承認フローの checkbox 初期ON/OFF も承認履歴で自動最適化される
# 候補一覧と承認フローには conf=[###--] 74% 形式の信頼度メーターも出る

# 実行履歴 / 整理ライブラリの「レビュー指示取り込み」
# review_package に入る FEEDBACK_TEMPLATE.md / txt / json / zip を取り込んで、
# 字幕置換・字幕ON/OFF・見どころ追加削除を手動微調整へ反映
# 反映前に差分プレビューが出る

# 出力設定に投稿先を入れると、投稿先テンプレートから推奨版を Variants へ追加できる
# 案件名も入っていれば、案件学習 + 投稿先学習をまとめて反映して sidebar の既定値を一括更新できる
# 候補学習の重みで、投稿先学習と案件学習の効き方を調整できる
# A/B比較の版候補は、投稿先学習の並びに加えて案件学習の推奨 variants で上段へ寄る
# A/B比較のタイトル候補 / 説明文候補も、案件学習の採用履歴で既定値と並び順が寄る
# 投稿先テンプレートが薄い時は、案件学習の採用投稿文本文と文体が投稿文テンプレートの初期値へ入る
# 学習重み自体も案件学習へ残るので、同じ案件名なら学習バランスも再利用できる
# 1.83.0 以降は、案件学習が run report から 字幕テンポ / カットテンポ / サムネ文字量 も拾う
# これらは明示設定を勝手に変えず、fallback として 字幕自然化の強さ / Final A/B Hook秒数 / Compose Style にだけ効く
# 1.84.0 以降は、この subtitle / cut tempo fallback が候補生成にも返る
# タイトル候補 / 説明文候補 / LLMメタデータ候補の文体が案件寄りに変わるが、現在の選択値は自動変更しない
# 1.85.0 以降は、same tempo hint が keep 範囲 / 見どころ候補 / LLM見どころ再評価にも返る
# つまり A/B候補の中身だけでなく、自動編集の切り方自体も案件寄りになる
# 1.86.0 以降は、same tempo hint が 章候補 / Hook Pack の版順 / サムネ文言候補 にも返る
# つまり chapter 見出し、完成動画A/Bの並び、composed thumbnail の文字面まで案件寄りになる

# デスクトップ起動（ポート競合を自動回避してブラウザを開く）
./tools/start_yt_tool_desktop.command

# 配布前インストール（.venv_yt_tool を作成）
./tools/install_yt_tool_app.command

# optional: pyannote まで入れる
./tools/install_yt_tool_app.sh --with-pyannote

# 配布用 bundle + zip を作成
python3 tools/package_yt_tool_bundle.py

# editor beta API + ブラウザ編集土台を起動
python3 -m pip install -r requirements-yt-tool-editor-beta.txt
./tools/start_editor_beta.command
# open http://127.0.0.1:8015/editor-beta

# 更新feedも埋め込んだ配布物を作成
python3 tools/package_yt_tool_bundle.py --release-base-url https://example.com/yt-tool

# 配布先で更新確認
./tools/check_yt_tool_updates.command
python3 yt_tool_desktop.py --check-updates

# 配布先で最新版を自動ダウンロードして別フォルダへ展開
./tools/apply_yt_tool_update.command
python3 yt_tool_desktop.py --apply-update

# 配布ガイド
open ./docs/YT_TOOL_DISTRIBUTION.md

# 操作説明書 / スペック表
open ./docs/YT_TOOL_OPERATION_MANUAL.md
open ./docs/YT_TOOL_SPEC_TABLE.md

# NGワード区間を自動ミュート + 話者色分け + サムネA/B強化
python3 yt_tool.py \
  --input /path/to/video.mp4 \
  --output-dir ./yt_tool_out \
  --base-name my_video \
  --ng-use-jp-preset \
  --ng-words "spoiler,ネタバレ" \
  --max-speakers 3 \
  --speaker-colors "FFFFFF,8BE9FF,FFD166" \
  --thumbnail-top-n 4 \
  --thumbnail-candidate-multiplier 4

# サムネ自動合成（raw サムネとは別に文字載せ済みサムネを生成）
python3 yt_tool.py \
  --input /path/to/video.mp4 \
  --output-dir ./yt_tool_out \
  --base-name my_video \
  --thumbnail-top-n 4 \
  --thumbnail-candidate-multiplier 4 \
  --thumbnail-compose-mode auto \
  --thumbnail-compose-top-n 3 \
  --thumbnail-compose-style impact \
  --thumbnail-compose-palette warm \
  --thumbnail-compose-position bottom \
  --thumbnail-compose-overlay-strength strong \
  --thumbnail-compose-auto-position-hint center \
  --thumbnail-compose-auto-overlay-strength-hint soft \
  --thumbnail-compose-font-file /path/to/font.ttf \
  --thumbnail-compose-template-file /path/to/template.png

# 完成動画A/B自動量産（見どころを冒頭へ移した Hook Pack 版を別出力）
python3 yt_tool.py \
  --input /path/to/video.mp4 \
  --output-dir ./yt_tool_out \
  --base-name my_video \
  --platform-profile shorts \
  --final-ab-mode hook_pack \
  --final-ab-hook-sec 2.5

# 字幕精度改善（初期プロンプト + 置換辞書）+ 字幕焼き込み(ffmpeg-full優先)
python3 yt_tool.py \
  --input /path/to/video.mp4 \
  --output-dir ./yt_tool_out \
  --base-name my_video \
  --prefer-ffmpeg-full \
  --subtitle-initial-prompt "固有名詞: OpenAI, ChatGPT, 九州商事" \
  --subtitle-replacements "Open AI=>OpenAI,えーっと=>えっと" \
  --subtitle-use-jp-cleanup

# BGM / SE 自動演出（Shorts / TikTok向け）
python3 yt_tool.py \
  --input /path/to/video.mp4 \
  --output-dir ./yt_tool_out \
  --base-name my_video \
  --platform-profile shorts \
  --bgm-mode auto \
  --bgm-volume-db -27 \
  --bgm-highlight-volume-db -23 \
  --se-mode auto \
  --se-volume-db -14 \
  --se-duration-sec 0.18 \
  --se-max-count 6

# 手持ち素材を使う場合
python3 yt_tool.py \
  --input /path/to/video.mp4 \
  --output-dir ./yt_tool_out \
  --base-name my_video \
  --bgm-mode asset \
  --bgm-file /path/to/bgm.mp3 \
  --se-mode asset \
  --se-file /path/to/hit.wav

# 被写体追従クロップで縦動画を書き出す
python3 yt_tool.py \
  --input /path/to/video.mp4 \
  --output-dir ./yt_tool_out \
  --base-name my_video \
  --export-variants 9:16,4:5 \
  --variant-fit-mode subject_track \
  --subject-track-sample-interval-sec 0.8 \
  --subject-track-max-samples 40

# 実話者分離（pyannote）を使う場合
export HUGGINGFACE_TOKEN=\"hf_xxx\"
python3 yt_tool.py \
  --input /path/to/video.mp4 \
  --output-dir ./yt_tool_out \
  --base-name my_video \
  --speaker-diarization pyannote \
  --min-speakers 1 \
  --max-speakers 4

# 声判定を参照サンプルで補正する場合（高め男性声対策）
python3 yt_tool.py \
  --input /path/to/video.mp4 \
  --output-dir ./yt_tool_out \
  --base-name my_video \
  --speaker-color-mode gender_auto \
  --gender-pitch-max-samples 8 \
  --gender-pitch-max-total-sec 24 \
  --reference-sample-quality-filter skip_ng \
  --gender-reference-samples "male=/path/to/male_1.wav|/path/to/male_2.mov;female=/path/to/female_1.wav|/path/to/female_2.mov"

# 名前付き話者参照で S1/S2 を実話者へ寄せる場合
python3 yt_tool.py \
  --input /path/to/video.mp4 \
  --output-dir ./yt_tool_out \
  --base-name my_video \
  --speaker-diarization auto \
  --speaker-color-mode gender_auto \
  --speaker-reference-profiles "自分=/path/to/me_1.wav|/path/to/me_2.mov;相手=/path/to/partner_1.wav|/path/to/partner_2.mov"

# pyannote固定話者モード（参照ラベル順に S1/S2 を固定）
export HUGGINGFACE_TOKEN=\"hf_xxx\"
python3 yt_tool.py \
  --input /path/to/video.mp4 \
  --output-dir ./yt_tool_out \
  --base-name my_video \
  --speaker-diarization pyannote_locked \
  --speaker-reference-profiles "自分=/path/to/me_1.wav|/path/to/me_2.mov;相手=/path/to/partner_1.wav|/path/to/partner_2.mov"

# 軽量固定話者モード（token不要、heuristicベース）
python3 yt_tool.py \
  --input /path/to/video.mp4 \
  --output-dir ./yt_tool_out \
  --base-name my_video \
  --speaker-diarization reference_locked \
  --speaker-reference-profiles "自分=/path/to/me_1.wav|/path/to/me_2.mov;相手=/path/to/partner_1.wav|/path/to/partner_2.mov"

# 話者固定色 + 自分だけクリップ
python3 yt_tool.py \
  --input /path/to/video.mp4 \
  --output-dir ./yt_tool_out \
  --base-name my_video \
  --speaker-diarization reference_locked \
  --speaker-reference-profiles "自分=/path/to/me_1.wav|/path/to/me_2.mov;相手=/path/to/partner_1.wav|/path/to/partner_2.mov" \
  --speaker-identity-color-lock \
  --speaker-identity-color-map "自分:7ED957,相手:4EA1FF" \
  --speaker-focus-clips \
  --speaker-focus-labels "自分"

# 話者ごとに字幕装飾を固定しつつ、自分の縦動画も出す
python3 yt_tool.py \
  --input /path/to/video.mp4 \
  --output-dir ./yt_tool_out \
  --base-name my_video \
  --speaker-diarization reference_locked \
  --speaker-reference-profiles "自分=/path/to/me_1.wav|/path/to/me_2.mov;相手=/path/to/partner_1.wav|/path/to/partner_2.mov" \
  --speaker-identity-color-lock \
  --speaker-identity-style-lock \
  --speaker-focus-clips \
  --speaker-focus-labels "自分" \
  --speaker-focus-variants "9:16,4:5"

# 話者別テンプレートとスマートクロップを明示指定する
python3 yt_tool.py \
  --input /path/to/video.mp4 \
  --output-dir ./yt_tool_out \
  --base-name my_video \
  --speaker-diarization reference_locked \
  --speaker-reference-profiles "自分=/path/to/me_1.wav|/path/to/me_2.mov;相手=/path/to/partner_1.wav|/path/to/partner_2.mov" \
  --speaker-identity-style-lock \
  --speaker-identity-style-map "自分:host,相手:guest" \
  --speaker-focus-clips \
  --speaker-focus-labels "自分,相手" \
  --speaker-focus-variants "9:16,4:5" \
  --speaker-focus-variant-fit smart_crop \
  --speaker-focus-crop-map "自分:left,相手:right"
```
`pyannote.audio` の導入と、Hugging Face側で対象モデル利用規約の同意が必要です。
※ `--speaker-diarization pyannote` を使わない場合、話者分離はヒューリスティック推定です。

主な出力:
- `*_final.mp4`: 自動編集済み本編
- `*_config.json`: 実行設定スナップショット
- `*.srt` / `*.ass`: 字幕ファイル
- `thumbnails/`: サムネ候補
- `*_thumbnail_ranking.json`: サムネA/B評価スコア
- `variants/`: 16:9 / 9:16 / 1:1 出力
- `highlight_clips/`: 見どころ短尺クリップ
- `*_metadata.json`: タイトル/説明/タグ候補
- `*_upload_manifest.csv`: 投稿用マニフェスト

## 0-1. Ubuntuクラウド初期セットアップ（一括）
```bash
chmod +x ./tools/cloud_ubuntu_setup.sh
./tools/cloud_ubuntu_setup.sh --with-secrets
# HTTPS公開を常駐する場合（ngrok systemdも同時導入）
./tools/cloud_ubuntu_setup.sh --with-secrets --with-ngrok-service
# 取引通知(notifier)も常駐する場合
./tools/cloud_ubuntu_setup.sh --with-secrets --with-ngrok-service --with-trade-notifier-service
# 週次レポート→AI学習反映も常駐する場合
./tools/cloud_ubuntu_setup.sh --with-secrets --with-ngrok-service --with-trade-notifier-service --with-weekly-autotrain-service
```

`--with-secrets` を外すと secrets 登録を後回しにできます。
`--skip-git-hook` を付けると commit履歴自動記録フックの導入をスキップできます。
`--with-ngrok-service` を付けると `ouroboros-ngrok.service` も有効化します。
`--with-trade-notifier-service` を付けると `ouroboros-trade-notifier.timer` も有効化します（ENTRY/EXIT・risk_stop・runner状態を通知）。
`--with-weekly-autotrain-service` を付けると `ouroboros-weekly-autotrain.timer` も有効化します（週次レポート生成 + AI学習設定反映 + 次回tickで再学習許可）。

MacからVMへ転送+実行を一括で行う場合:
```bash
VM_HOST=161.33.26.35
VM_KEY=/Users/tani/Downloads/ssh-key-2026-03-04-4.key
chmod +x ./tools/deploy_to_ubuntu_vm.sh
./tools/deploy_to_ubuntu_vm.sh --host "$VM_HOST" --key "$VM_KEY" --with-secrets
```
VM再作成で接続先が変わったら `VM_HOST` と `VM_KEY` の両方を見直してください。

差分ファイルだけを高速反映する場合:
```bash
VM_HOST=161.33.26.35
VM_KEY=/Users/tani/Downloads/ssh-key-2026-03-04-4.key
chmod +x ./tools/deploy_vm_components.sh

# drift監視 + 週次autotrain を反映して、そのまま systemd 再反映まで実行
./tools/deploy_vm_components.sh \
  --host "$VM_HOST" \
  --key "$VM_KEY" \
  --with-drift-watch --with-weekly-autotrain

# widget status をVM常駐化する場合
./tools/deploy_vm_components.sh \
  --host "$VM_HOST" \
  --key "$VM_KEY" \
  --with-widget-status
```

## 1. 最短起動（まずこれ）
### 1-1. ダッシュボードをHTTPS公開（iPhone対応）
```bash
./tools/start_dashboard_ngrok.sh
```

### 1-1a. iPhoneホーム画面アイコンを固定（2番: アプリ側指定）
```bash
# 1) 使いたい画像を配置（推奨: 1024x1024 PNG）
cp /path/to/your_icon.png ./.streamlit/assets/apple-touch-icon.png

# 2) dashboard再起動
sudo systemctl restart ouroboros-dashboard.service
# ローカル実行中なら streamlit を再起動
```

`MAIN/.streamlit/secrets.toml` の既定:
```toml
[dashboard_branding]
apple_touch_icon_path = ".streamlit/assets/apple-touch-icon.png"
apple_mobile_web_app_title = "Project Ouroboros"
```

iPhone側はアイコンがキャッシュされるため、既存のホーム画面ショートカットを削除して再追加してください。

### 1-1b. ngrok URL変更時に `redirect_uri` とアイコン設定を自動同期
```bash
python3 tools/sync_dashboard_ngrok_secrets.py --ensure-branding
```

systemd運用で反映まで一発でやる場合:
```bash
python3 tools/sync_dashboard_ngrok_secrets.py --ensure-branding --restart-dashboard-service
```

備考:
- `redirect_uri` は `http://127.0.0.1:4040/api/tunnels` から自動取得した HTTPS URL に更新されます
- `[dashboard_branding]` が無い場合は自動作成されます（既存値は上書きしません）
- `tools/start_dashboard_ngrok.sh` 実行時も同同期処理が自動実行されます

### 1-1c. 簡易ステータス面（Mac / iPhone）
```bash
# まずはCLIで内容確認
python3 tools/widget_status.py --print-text

# Web版を起動（同一Wi-FiのiPhoneからも見られる）
WIDGET_STATUS_HOST=0.0.0.0 ./tools/start_widget_status_server.sh
```

用途:
- デスクトップの常時表示: `MAIN/widget/swiftbar/ouroboros.1m.sh`
- iPhoneホーム画面のコンパクト表示: `MAIN/WIDGETS.md`

Scriptable を iPhone に反映する最短:
```bash
./tools/publish_scriptable_widget.sh
```

常駐化:
```bash
./tools/install_widget_status_launchagent.sh \
  --host 0.0.0.0 \
  --port 8787 \
  --token 'change-this-token' \
  --replace-running
```

Ubuntu / VM に移して、PCを閉じていても見たい場合:
```bash
# 1) token を cloud secrets に入れる
echo "WIDGET_STATUS_TOKEN='change-this-token'" | sudo tee -a /etc/ouroboros/secrets.env
sudo chmod 600 /etc/ouroboros/secrets.env

# 2) service を反映
./tools/install_systemd_services.sh --with-widget-status
sudo systemctl restart ouroboros-widget-status.service

# 3) 動作確認
sudo systemctl status ouroboros-widget-status.service --no-pager -l
curl "http://127.0.0.1:8787/widget-status.json?token=change-this-token"
```

外から直接見る場合は、cloud 側で `TCP 8787` の ingress も開けてください。
Scriptable の `Parameter` は次の形です:

```json
{"baseUrls":["http://<VM_PUBLIC_IP>:8787"],"token":"change-this-token"}
```

### 1-2. ローカルだけで見る
```bash
python3 -m streamlit run dashboard.py
```

### 1-2b. 競馬予想アプリ（研究MVP）
```bash
python3 -m streamlit run keiba_dashboard.py
```

CSVを使わず試す場合は、アプリ内の「サンプルデータを使う」をONのまま `予想を実行` してください。

起動判定:
- `Local URL: http://localhost:8501` が表示されたら起動成功です
- 停止するまでこのターミナルは開いたままにしてください（`Ctrl+C` で停止）

### 1-2c. JRA/NAR CSV をアプリ形式へ整形
```bash
# 履歴データ
python3 tools/normalize_keiba_csv.py \
  --mode history \
  --in ./data/jra_history_raw.csv \
  --out ./data/jra_history_normalized.csv

# 出走馬データ（天気/馬場/距離を補完）
python3 tools/normalize_keiba_csv.py \
  --mode entries \
  --in ./data/jra_entries_raw.csv \
  --out ./data/jra_entries_normalized.csv \
  --default-weather 晴 \
  --default-track 良 \
  --default-distance 1600
```

### 1-2d. 週次で重み最適化（回収率ベース）
```bash
python3 tools/tune_keiba_feature_weights.py \
  --history ./data/jra_history_normalized.csv \
  --out ./data/keiba_best_weights.json \
  --trials 40 \
  --val-races 30 \
  --simulations 1500
```

生成された `keiba_best_weights.json` は `keiba_dashboard.py` のサイドバー「重みJSON（任意）」で読み込めます。

### 1-2e. 完全分離版（KEIBA専用アプリ）
トレード系と分離して軽く使いたい場合:
```bash
cd ~/trading_bot/trading_bot/KEIBA
./run_keiba.sh
```

開くURL: `http://127.0.0.1:8511`

外から無料で見る場合:
```bash
cd ~/trading_bot/trading_bot/KEIBA
brew install cloudflared
./start_public.sh
```

公開URLはターミナルとアプリのサイドバーに表示されます。
`cloudflared` が入っていればそれを優先し、なければ `ngrok` にフォールバックします。
`ngrok` を明示したい場合:
```bash
cd ~/trading_bot/trading_bot/KEIBA
brew install ngrok
ngrok config add-authtoken <YOUR_TOKEN>
PUBLIC_PROVIDER=ngrok ./start_public.sh
```

固定URLで安定運用したい場合:
```bash
cd ~/trading_bot/trading_bot/KEIBA
brew install cloudflared
./setup_named_tunnel.sh
cloudflared tunnel login
cloudflared tunnel create keiba
cloudflared tunnel route dns keiba keiba.example.com
# KEIBA/.cloudflared/keiba_named_tunnel.env を埋める
PUBLIC_PROVIDER=cloudflared_named ./start_public.sh
```

止めずに使う常駐化:
```bash
cd ~/trading_bot/trading_bot/KEIBA
./install_public_launchagent.sh
launchctl print gui/$(id -u)/com.ouroboros.keiba.public
./keiba_public_healthcheck.sh
```

異常時通知:
```bash
cd ~/trading_bot/trading_bot/KEIBA
./install_public_watch_launchagent.sh
cp .streamlit/keiba_public_notify.example.json .streamlit/keiba_public_notify.json
# 必要なら ntfy / webhook を書く
launchctl print gui/$(id -u)/com.ouroboros.keiba.public.watch
```

監視は既定で 60 秒ごとです。
監視は Quick Tunnel の URL変更も検知し、不健康時は既定で自動再起動を試みます。

常駐停止:
```bash
cd ~/trading_bot/trading_bot/KEIBA
./uninstall_public_launchagent.sh
```

今週レース+過去レースを自動取得して学習最適化まで実行:
```bash
cd ~/trading_bot/trading_bot/KEIBA
pip install keibascraper
# 初回（フル寄り）
python3 tools/auto_update_data.py --months-back 24 --weekly-days-ahead 7 --run-tuning

# 2回目以降（高速: 最新追記）
python3 tools/auto_update_data.py --months-back 24 --weekly-days-ahead 7 --incremental --append-only --history-backfill-days 0 --entries-cache-hours 4
```

CLIを使わず画面内だけで完結する場合:
- サイドバー `最新だけ更新` で最新データだけ追記（最速）
- `天気予報を自動取得して反映` で今週レース天気を自動更新
- `更新後に今週AI予想を自動作成` で全レース本命一覧を自動生成
- 必要時だけ `学習だけ実行` または `取得→学習→予想を一括実行` を使用
- `ページ起動時に自動更新（1セッション1回）` をONにすると、画面を開くたびに自動取得

### 1-3. botを安全起動/停止（CLI）
```bash
./tools/safe_start_bot.sh                 # PAPER想定（推奨）
./tools/safe_start_bot.sh --allow-live    # LIVE候補時のみ明示許可
./tools/safe_stop_bot.sh                  # 安全停止
./tools/safe_stop_bot.sh --force-kill     # どうしても止まらない時のみ
```

## 2. ダッシュボードの基本導線（CLI不要）
1. `🏠 ホーム・稼働状況` で状態確認
2. `🚀 実行・緊急操作` で bot 起動/停止（2段階ガード）
3. `⚙️ Bot設定` で CONTROL を保存
4. `📊 成績・分析` で daily_report / audit
5. `🧪 Shadow起動/停止` で並行検証

## 2-1. ダッシュボード認証の強化（他人ログイン防止）
`MAIN/.streamlit/secrets.toml` の `dashboard_security` に許可リストを設定:

```toml
[dashboard_security]
login_notify_enabled = true
auth_fail_notify_enabled = true
allowed_emails = ["owner@example.com"]
allowed_email_domains = ["example.com"]
ntfy_topic_url = "https://ntfy.sh/<PRIVATE_TOPIC>"
```

ポイント:
- `allowed_emails` / `allowed_email_domains` が空だと、OIDC設定済みユーザーはログイン可能になります
- ローカルbreakglassは緊急時のみ利用（`dashboard_auth.json` で制御）
- `ツール` タブの `ログイン監査履歴` で「誰が/いつ/どこから」を確認できます

CLIで監査ログ確認:
```bash
tail -n 50 .streamlit/dashboard_login_audit.jsonl
```

## 3. 日次の安全チェック（LIVE前）
### 3-1. API・残高・権限
```bash
python3 tools/live_preflight.py
```

### 3-2. 総合チェック
```bash
./run_check.sh
```

### 3-2a. 反転直後の飛び乗り抑制（2026-03-29 追加）
`CONTROL.csv` で次の3項目を使えます。

```text
buy_fast_ma_distance_pct=0.12
trend_flip_cooldown_min=10
canary_tp_scale=0.65
news_entry_block_ahead_min=60
pre_news_exit_buffer_min=10
pre_news_exit_min_hold_min=5
```

意味:
- `buy_fast_ma_distance_pct`: BUY時に価格が fast MA に近すぎると見送り（現行は 0.12。4/2 の 0.1189% 近接 BUY を止めるため少し強化）
- `trend_flip_cooldown_min`: `DOWN->UP` / `UP->DOWN` 直後の新規エントリー待機時間（分）
- `canary_tp_scale`: CANARY時だけ `tp_buy_pct` / `tp_sell_pct` を縮める倍率
- `news_entry_block_ahead_min`: 昼休み/ニュース帯がこの分数以内に迫っていたら新規エントリーを見送る
- `pre_news_exit_buffer_min`: 昼休み/ニュース帯の何分前から既存ポジションを手仕舞い対象にするか
- `pre_news_exit_min_hold_min`: 建てた直後の即クローズを避けるため、最低保有分数を設ける

### 3-2b. 週次レポート生成（JSON）
```bash
# day8から週を自動決定
python3 weekly_report.py 20260304

# 明示レンジ
python3 weekly_report.py 20260301-20260307

# strict（WARNでも失敗）
python3 weekly_report.py 20260301-20260307 --strict
```

週次のAI提案だけ確認:
```bash
python3 - <<'PY'
import json
from pathlib import Path
p=Path("weekly_report_out/weekly_report_20260302_20260308.json")
d=json.loads(p.read_text(encoding="utf-8"))
print(json.dumps(d.get("ai_feedback", {}).get("suggested_control_updates", {}), ensure_ascii=False, indent=2))
PY
```

### 3-2c. Dashboardで「週次提案の反映前後比較」を使う（運用推奨）
1サイクルの流れ:
1. `📊 成績・分析` で対象日を選ぶ（週単位推奨）
2. `▶ weekly_report 実行`
3. `AI学習提案` の内容を確認して `🧠 AI学習設定へ提案を反映`
4. 次回のAI自動学習が走った後、同画面の `🧪 週次提案の反映前後比較` を確認
5. `current_metric / best_metric / backtest_pf / backtest_expectancy` の delta と `status` を見る

`status` の意味:
- `UP`: 改善
- `DOWN`: 悪化
- `SAME`: 変化なし
- `REF`: 参考値（判定対象外）
- `CHANGED`: 文字列理由が変更

注意点:
- 反映直後は `比較待機中` が正常（after未更新）
- 同じ日に何度も反映すると比較基準が上書きされる
- 再検証したい場合は `比較スナップショットをクリア` で基準を初期化

### 3-2d. 週次レポート→AI学習設定反映をCLIで自動化
```bash
# 前週(MON-SUN)を自動計算して実行（提案値をCONTROLに反映 + 次回tickで再学習許可）
python3 tools/weekly_auto_feedback.py --mode previous-week --apply-control --reset-auto-train-day

# ドライラン（書き込みなし）
python3 tools/weekly_auto_feedback.py --mode previous-week --apply-control --reset-auto-train-day --dry-run --print-suggested

# Ollama要約を強制実行（失敗しても週次処理は継続）
python3 tools/weekly_auto_feedback.py --mode previous-week --apply-control --reset-auto-train-day --llm-mode ollama

# LLM無効化（従来挙動）
python3 tools/weekly_auto_feedback.py --mode previous-week --apply-control --reset-auto-train-day --llm-mode off

# 現行推奨（このVMでは週次は0.5bを優先）
python3 tools/weekly_auto_feedback.py --mode previous-week --apply-control --reset-auto-train-day --llm-mode auto --ollama-model qwen2.5:0.5b --ollama-timeout-sec 180

# クラウドLLMで週次だけ強化（APIキーは環境変数で渡す）
export OPENAI_API_KEY='...'
python3 tools/weekly_auto_feedback.py --mode previous-week --apply-control --reset-auto-train-day --llm-mode openai --openai-model gpt-5.4-mini
```

Ollama接続先/モデルの指定（任意）:
```bash
export OUROBOROS_OLLAMA_BASE_URL="http://127.0.0.1:11434"
export OUROBOROS_OLLAMA_MODEL="qwen2.5:0.5b"
```

無料ローカルLLM（Ollama）をUbuntuへ導入:
```bash
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl enable --now ollama
ollama --version
ollama pull qwen2.5:0.5b
# 日次反省を少し強めたい時
ollama pull qwen2.5:1.5b

# 接続確認（モデル一覧）
curl -s http://127.0.0.1:11434/api/tags | jq '.models[].name'
```

補足:
- `--llm-mode auto`（既定）は、Ollama未導入/未起動でも週次処理自体は止まりません（LLM要約だけスキップ）。
- 現行VMでは、週次要約は `qwen2.5:0.5b` が安定です。`1.5b` は長い週次プロンプトで timeout しやすいため、日次反省だけ `1.5b` を使う構成を推奨します。
- 生成要約は `state.json` の `_weekly_auto_feedback.llm_feedback` に保存されます。
- 週次 LLM は `shadow` 週次も自動比較し、`_weekly_auto_feedback.shadow_weekly_review` に `昇格候補 / 保留 / 差し戻し / 評価保留` を保存します。
- `shadow` 比較は既定で `../logs/instances/shadow` を見ます。変更する場合は `--shadow-logs-dir` を指定します。
- 日次反省は `loss_pattern_breakdown` を見て、`反転巻き込み / 伸び不足 / entry遅れ` の支配的な負け型を通知と LLM prompt に含めます。
- 日次反省は `opportunity_pattern_breakdown` も見て、`entry約定失敗 / exit取り逃し / 時間帯回避 / 時間ブロック / spread回避` の支配的な機会損失も通知と LLM prompt に含めます。
- 週次 LLM は `main` と `shadow` の負け型・機会損失の差分も見て、`shadow_weekly_review.pattern_hint` と `pattern_reason` に「昇格前に何が足りないか」を残します。
- widget / Web の `今週累計` は `shadow_weekly_review.decision / pattern_hint` も拾うので、`保留 / entry品質不足` のような週次ヒントを一目で確認できます。
- shadow では `weak_progress_exit_enabled=1 / weak_progress_exit_min_hold_min=30 / weak_progress_exit_max_best_fav_pct=0.05` を使い、30分以上持っても `best_fav<0.05%` の flat な TIMEOUT 候補だけ早めに畳んでいます。
- shadow ではさらに `progress_reversal_exit_enabled=1 / progress_reversal_exit_min_hold_min=20 / progress_reversal_exit_min_best_fav_pct=0.08 / progress_reversal_exit_max_current_fav_pct=0.03` を使い、一度進んだ玉が `current_fav<=0.03%` まで戻したら `PROGRESS_REVERSAL` で早めに逃がします。
- shadow では `no_follow_through_exit_enabled=1 / no_follow_through_exit_min_hold_min=5 / no_follow_through_exit_max_best_fav_pct=0.01 / no_follow_through_exit_max_current_fav_pct=0.00` も使い、5分経っても初動でまったく伸びない玉を `NO_FOLLOW_THROUGH` として先に畳みます。
- 日次反省の `【反省】` と LLM の `翌日:` は `shadow調整=filter=... / exit=...` を持ち、`WEAK_PROGRESS / PROGRESS_REVERSAL` についても `維持寄り / 少し早め候補 / 観察寄り / 現状維持` で読めます。
- widget の `Reflection` detail と large widget 下段も同じ `shadow調整` を読むので、通知を開かなくても `filter / exit` の方向だけは確認できます。

### 3-2e. 日次で再学習トリガーを明示的に入れる（任意）
```bash
# state._ai_auto_train_day を空に戻し、次tickでAI再学習を許可
python3 tools/daily_auto_train_reset.py --state-path state.json --control-path CONTROL.csv

# ドライラン
python3 tools/daily_auto_train_reset.py --dry-run

# 同日でも強制リセットしたい場合
python3 tools/daily_auto_train_reset.py --force
```

### 3-2f. Champion/Challenger 昇格判定（任意）
```bash
# 判定だけ（昇格しない）
python3 tools/champion_challenger_promote.py --lookback-days 14

# 判定OK時のみ、shadow の閾値を本番 ai_model.json へ昇格
python3 tools/champion_challenger_promote.py --lookback-days 14 --apply

# 強制昇格（通常は非推奨）
python3 tools/champion_challenger_promote.py --lookback-days 14 --apply --force-promote
```

### 3-2g. Championロールバック監視（任意）
```bash
# 判定だけ（ロールバックしない）
python3 tools/champion_rollback_guard.py --lookback-days 7

# 閾値悪化時のみ、昇格前閾値へ自動復帰
python3 tools/champion_rollback_guard.py --lookback-days 7 --apply
```

### 3-2h. ドリフト監視（任意）
```bash
# 判定のみ（状態記録だけ）
python3 tools/market_drift_watch.py --recent-days 3 --baseline-days 14

# ALERT時に ai_auto_train_enabled=0 へ自動切替
python3 tools/market_drift_watch.py --recent-days 3 --baseline-days 14 --apply-train-freeze

# ALERTで凍結し、NORMAL復帰時に自動解除まで行う
python3 tools/market_drift_watch.py --recent-days 3 --baseline-days 14 --apply-train-freeze --auto-unfreeze

# ALERTで学習停止 + 取引停止、NORMAL復帰で両方自動再開（drift由来停止時のみ）
python3 tools/market_drift_watch.py --recent-days 3 --baseline-days 14 --apply-train-freeze --auto-unfreeze --apply-trade-pause --auto-resume-trade

# ALERT要因を時間帯別に分析し、悪い時間帯を no_paper_hours に自動反映（NORMAL時に元へ戻す）
python3 tools/market_drift_watch.py --recent-days 3 --baseline-days 14 --apply-train-freeze --auto-unfreeze --apply-trade-pause --auto-resume-trade --apply-hour-block --auto-unblock-hours

# 復帰をやや緩和 + リスクガード強化
python3 tools/market_drift_watch.py --recent-days 3 --baseline-days 14 --min-recent-closed 6 --min-baseline-closed 25 --pf-drop-th 0.15 --avg-ret-drop-th 0.02 --win-rate-drop-th 6 --apply-train-freeze --auto-unfreeze --apply-trade-pause --auto-resume-trade --apply-hour-block --auto-unblock-hours --hour-block-max-hours 8 --hour-block-avg-ret-th 0.00 --hour-block-win-rate-th 45 --apply-risk-tighten --auto-restore-risk --risk-alert-daily-loss-limit-pct -0.30 --risk-alert-streak-max-losses 2 --resume-require-consecutive-normal 4

# INSUFFICIENT が続く時に no_paper_hours を段階的に緩和（保護を残したままサンプル回収）
python3 tools/market_drift_watch.py --recent-days 3 --baseline-days 14 --min-recent-closed 6 --min-baseline-closed 25 --pf-drop-th 0.15 --avg-ret-drop-th 0.02 --win-rate-drop-th 6 --apply-train-freeze --auto-unfreeze --apply-trade-pause --auto-resume-trade --apply-hour-block --auto-unblock-hours --hour-block-max-hours 8 --hour-block-avg-ret-th 0.00 --hour-block-win-rate-th 45 --apply-risk-tighten --auto-restore-risk --risk-alert-daily-loss-limit-pct -0.30 --risk-alert-streak-max-losses 2 --resume-require-consecutive-normal 4 --resume-canary-runs 2 --insufficient-auto-relax-hours --insufficient-relax-after-runs 4 --insufficient-relax-drop-hours 1 --insufficient-relax-max-applies 2 --backup-dir backups/drift_watch --backup-max-keep 50 --lock-file /tmp/ouroboros-drift-watch.lock
```

運用メモ:
- `resume_require_consecutive_normal` を上げるほど、再開が慎重になります。
- systemd既定は `30分ごと` 実行 + `--resume-require-consecutive-normal 4`（約2時間のNORMAL継続が必要）です。
- `resume-canary-runs=2` により、復帰直後は厳しめ risk 設定を 2 run 維持してから元に戻します。
- `INSUFFICIENT` 継続時は既定で `4連続` ごとに `no_paper_hours` を `末尾1時間` ずつ緩和します（最大2回）。
- `--lock-file` で二重実行を自動スキップします（timer と手動起動の競合対策）。
- `--backup-dir` へ `CONTROL.csv` / `state.json` の更新前スナップショットを世代保存します。
- 既定のdrift gateは安全側に寄せています: `min_recent_closed=6`, `min_baseline_closed=25`, `pf_drop_th=0.15`, `avg_ret_drop_th=0.02`, `win_rate_drop_th=6`, `hour_block_max_hours=8`, `hour_block_avg_ret_th=0.00`, `hour_block_win_rate_th=45`。
- 既定のrisk tightenは `daily_loss_limit_pct=-0.30`, `streak_stop_enabled=1`, `streak_stop_max_losses=2` を ALERT 中に適用し、NORMAL復帰時（連続条件クリア後）に元値へ戻します。

### 3-3. 通知（任意）
```bash
python3 tools/trade_event_notifier.py --dry-run
```

`PAPER_EXIT_*` 通知には `ret_pct / pnl_jpy / evaluation(GOOD|BAD|NEUTRAL)` が含まれます。
さらに `state.json` の期待値が取れる場合は `expectancy_ref_pct / expectancy_delta_pct / vs_expectancy(ABOVE|NEAR|BELOW)` も通知します。

通知の追加設定（`.streamlit/secrets.toml` の `[dashboard_security]`）:
```toml
# 連敗アラート
trade_notify_loss_streak_enabled = true
trade_notify_loss_streak_threshold = 3

# 日次損益アラート（ret_pct合計）
trade_notify_daily_loss_enabled = true
trade_notify_daily_loss_limit_pct = 0.50
trade_notify_auto_disable_trade_enabled = false

# 終業レポート（runner OFF 後に1日1回）
trade_notify_daily_goal_report_enabled = true
trade_notify_daily_goal_jpy = 100
# ローカル/VM LLMで反省メモを補強する場合
trade_notify_daily_reflection_llm_mode = "auto"   # off / auto / ollama / openai
trade_notify_daily_reflection_llm_provider = "ollama"  # ollama / openai
trade_notify_daily_reflection_ollama_base_url = "http://127.0.0.1:11434"
trade_notify_daily_reflection_ollama_model = "qwen2.5:1.5b"
trade_notify_daily_reflection_ollama_timeout_sec = 240
trade_notify_daily_reflection_ollama_max_chars = 650
# OpenAI Responses API を使う場合。APIキー本体は secrets.toml へ直書きせず、VM の環境変数に入れる。
trade_notify_daily_reflection_openai_base_url = "https://api.openai.com/v1"
trade_notify_daily_reflection_openai_model = "gpt-5.4-mini"
trade_notify_daily_reflection_openai_api_key_env = "OPENAI_API_KEY"
trade_notify_daily_reflection_openai_max_output_tokens = 320

# 日次反省の自動承認（安全な key だけ自動反映）
trade_notify_daily_reflection_auto_apply_enabled = true
trade_notify_daily_reflection_auto_apply_keys = "ai_train_weekly_bad_hours,no_paper_hours"
trade_notify_daily_reflection_auto_apply_min_confidence = "high"   # high / medium / low
trade_notify_daily_reflection_auto_apply_max_changes = 2
trade_notify_daily_reflection_auto_apply_approver = "notifier_auto_safe"

# 一定時間ノートレード
trade_notify_no_trade_enabled = true
trade_notify_no_trade_minutes = 60

# サービス死活
trade_notify_service_watch_enabled = true
trade_notify_watch_dashboard = true
trade_notify_watch_ngrok = false
# drift監視の状態変化通知
trade_notify_drift_watch_enabled = true

# 同種通知の最短再通知間隔（秒）
# 既定: trade_notify_min_interval_sec=180
trade_notify_min_interval_sec = 180
# アラート系（連敗/日次損失/ノートレード/自動停止）
trade_notify_alert_min_interval_sec = 180
# 状態変化系（dashboard/ngrok/runner/risk_stop/drift）
trade_notify_state_change_min_interval_sec = 180
```

`trade_notify_daily_goal_report_enabled=true` の場合、`runner_alive` が `ON -> OFF` になったあとに、
その日の `実現損益(JPY)` / `決済件数` / `目標100円の達成可否` を 1 日 1 回通知します。
さらに `勝因メモ / 敗因メモ / 翌日アクション / 翌日推奨設定` を本文に付け、`daily_report_out/daily_reflection_YYYYMMDD.json` に保存します。
常駐 runner 運用では `runner_alive OFF` にならないため、現在は `SKIP_OUT_OF_TIME` 到達時、または日付跨ぎ時の未送信補完でも終業レポートを送ります。
本文には `信頼度 / PF / avg_ret / 良悪時間帯 / best-worst trade` も付けます。サンプルが薄い日は、自動の設定変更は極力抑えて継続観察を優先します。
Mac側でVMスナップショットを使って確認する場合、`trade_event_notifier.py` は通常ログが空なら `.local_llm/vm_snapshot/latest/logs` を日次反省の参照元にできます。反省JSONの `daily_review.report_log_source=vm_snapshot` ならVM実ログ基準です。
`trade_notify_daily_reflection_auto_apply_enabled=true` を使うと、反省 JSON の `suggested_control_updates` のうち allowlist に入った key だけを自動反映できます。現在の安全運用は `ON` ですが、通知本文には毎回 `自動承認=...` が出るため、反映有無はその場で追えます。
安全側の推奨は `ai_train_weekly_bad_hours,no_paper_hours` だけを allowlist にして、`min_confidence=high` のまま使う構成です。`daily_loss_limit_pct` や `streak_stop_*` は手動承認のままを維持します。

`trade_notify_daily_reflection_llm_mode=auto|ollama` を使う場合は、`trade_event_notifier.py` が動くホストから `ollama` に到達できる必要があります。
VM 上の notifier で使うなら VM 上に Ollama を入れるか、到達可能な `ollama_base_url` を指定してください。
クラウドLLMを使う場合は `trade_notify_daily_reflection_llm_provider="openai"` または `trade_notify_daily_reflection_llm_mode="openai"` にし、VM 側の `OPENAI_API_KEY` 環境変数を設定します。失敗時は通知処理を止めず、`auto` なら Ollama/fallback へ落ちます。

週次だけ OpenAI Responses API で試す場合:
```bash
export OPENAI_API_KEY='...'
python3 tools/weekly_auto_feedback.py \
  --mode previous-week \
  --apply-control \
  --reset-auto-train-day \
  --llm-mode openai \
  --openai-model gpt-5.4-mini
```

翌日推奨設定の承認フロー:
```bash
# 最新の反省提案を確認
python3 tools/apply_daily_reflection.py

# 指定日の提案を確認
python3 tools/apply_daily_reflection.py 20260318

# 承認して CONTROL.csv に反映
python3 tools/apply_daily_reflection.py 20260318 --apply-control
```

### 3-4. まとめて安全チェック（推奨）
```bash
./tools/safe_guard.sh
```

オプション:
```bash
./tools/safe_guard.sh --skip-live-preflight
./tools/safe_guard.sh --skip-run-check
```

### 3-4b. 朝の自動再開チェック
```bash
# 判定だけ
python3 tools/morning_start_guard.py --print-json

# 営業開始前20分〜開始後5分の窓で、安全なら today_on / trade_enabled を戻す
python3 tools/morning_start_guard.py --auto-enable-today-on --auto-enable-trade

# bot service が死んでいたら起動、通知も送る
python3 tools/morning_start_guard.py --auto-enable-today-on --auto-enable-trade --start-bot-service --notify
```

注意:
- VM でこの CLI を一般ユーザーの shell から直実行すると、`live_preflight` が `/etc/ouroboros/secrets.env` を読めず `preflight_failed` に見えることがあります。
- 本番の systemd service は `EnvironmentFile=-/etc/ouroboros/secrets.env` を読むので、朝 timer の実運用とは挙動が揃っています。

安全に再開する条件:
- `paper_mode=0`
- `live_enabled=1`
- `observe_only=0`
- `safety_hard_block=0`
- `state.json` の `_risk_stop=OFF`
- `state.json` の `_streak_stop=OFF`
- `state.json` の `_drift_watch.status=NORMAL`
- `trade_paused_by_drift` 中は drift watch 側の復帰条件を優先

補足:
- 既定では `drift=INSUFFICIENT` でも、`trade_paused_by_drift=false` かつ不足が軽い時だけ朝の `sample_collection` 再開を許可します。
- 既定の目安は `remaining_samples <= 4` で通常の `sample_collection`、`remaining_samples <= 6` で深い回復モードです。
- さらに `0/6` のような深い不足でも、既定では `remaining_samples <= 6` の範囲なら朝だけ `deep sample_collection` を許可し、同時に `daily_loss_limit_pct=-0.30 / streak_stop_enabled=1 / streak_stop_max_losses=2` へ一時的に締めます。
- この tighten は `state._drift_watch` に退避されるので、後で drift watch の復帰処理で元へ戻せます。
- 完全に手動停止を維持したい日は、`trade_enabled=0` だけに頼らず `observe_only=1` か `safety_hard_block=1` を使う方が安全です。

## 4. Shadow（並行検証）
Shadowは本番と完全分離のため、安全に比較検証できます。

### 起動/停止
```bash
./tools/start_shadow_paper.sh        # 5分間隔
./tools/start_shadow_paper.sh 120    # 2分間隔
./tools/stop_shadow_paper.sh
```

### 分離先
- CONTROL: `MAIN/CONTROL_shadow.csv`
- STATE: `MAIN/state_shadow.json`
- LOCK: `MAIN/.run_lock_shadow/`
- LOG: `logs/instances/shadow/trade_log_YYYYMMDD.csv`

### 4-1. 現在の shadow 先行検証
- `exit_technical_enabled=1`
  - reversal の早期 exit を shadow だけで先行検証
- `trend_strength_filter_enabled=1`
  - `trend_strength_lookback_n=20`
  - `trend_strength_min_er=0.28`
  - 弱い/ジグザグ相場は `OBSERVE_TREND_STRENGTH_WEAK` で見送り、main へ上げる前に shadow で件数を確認する
- `HTF context`
  - `htf15_context_enabled=1`
  - `htf60_context_enabled=1`
  - `htf_context_lookback_n=8`
  - `htf_bias_slope_pct=0.02`
  - `htf60_countertrend_penalty=0.20`
  - `htf15_60_conflict_penalty=0.25`
  - `ai_use_htf_context=1`
  - 15分足は `bias / trendline / channel`、60分足は `bias` だけを shadow の AI 判定へ足して、5分足の逆行エントリーを減らせるかを見る
  - さらに **`15分足は順でも 60分足が逆`** の玉には追加ペナルティを入れて、4/10 の `14:27 BUY` のようなねじれエントリーを通しにくくする
- `no_follow_through_exit_enabled=1`
  - `no_follow_through_exit_min_hold_min=5`
  - `no_follow_through_exit_max_best_fav_pct=0.01`
  - `no_follow_through_exit_max_current_fav_pct=0.00`
  - HTF同方向でも初動がまったく出ない玉を `NO_FOLLOW_THROUGH` として shadow だけ早めに畳み、SLまで待つ必要があるかを検証する
- `MR observe layer`
  - `bot.py` には `OBSERVE_MR / OBSERVE_MR_FILTER_NG / OBSERVE_MR_TRIGGER` を追加済み
  - ただし安全のため **`observe_only=1` かつ `mr_observe_enabled=1` の時だけ** 発火する
  - 既定では OFF なので、今の main / shadow 売買ロジックは変わらない
  - 最初は専用 observe 用に以下だけ入れて note 品質を確認する

```text
observe_only=1
mr_observe_enabled=1
mr_level_lookback_n=24
mr_spike_lookback_n=12
mr_spike_min_move_pct=0.18
mr_touch_tolerance_pct=0.08
mr_ma_cross_lookback_n=16
mr_range_max_ma_slope_pct=0.08
mr_range_max_ma_gap_pct=0.18
mr_stop_min_distance_pct=1.0
mr_paper_enabled=1
mr_paper_min_rank=A
mr_paper_require_trigger=1
mr_paper_require_reclaim=1
htf15_context_enabled=1
htf60_context_enabled=1
htf_context_lookback_n=8
htf_bias_slope_pct=0.02
```

  - note には `strategy=MR / mr_score / mr_rank / mr_level_type / mr_reclaim / mr_stop_pct / mr_htf15_bias / mr_htf15_trendline / mr_htf15_channel_pos / mr_htf60_bias` などを埋め込む
  - Phase 1 は観測のみ。2026-04-29 から Phase 1.5 として **MR専用runnerだけ** `Aランク + OBSERVE_MR_TRIGGER + mr_reclaim=1` をPAPER建玉化する
  - `observe_mr_paper_enabled=1` は `mr_paper_enabled=1` の互換aliasとして読める

### 4-2. MR observe 専用インスタンス
MR は `main` と `shadow` へ混ぜず、別 instance で observe/PAPER ログを貯める。

### 起動/停止
```bash
./tools/start_mr_observe.sh        # 5分間隔
./tools/start_mr_observe.sh 120    # 2分間隔
./tools/stop_mr_observe.sh
```

### 分離先
- CONTROL: `MAIN/CONTROL_mr_observe.csv`
- STATE: `MAIN/state_mr_observe.json`
- LOCK: `MAIN/.run_lock_mr_observe/`
- LOG: `logs/instances/mr_observe/trade_log_YYYYMMDD.csv`

### 運用メモ
- `observe_only=1` と `mr_observe_enabled=1` は固定
- `paper_mode=1 / live_enabled=0`
- 既存main/shadow戦略の売買は発生しない
- `mr_paper_enabled=1` の時だけ、`mr_rank=A` かつ `OBSERVE_MR_TRIGGER` かつ `mr_reclaim=1` を `PAPER` に昇格する
- まず見るのは `OBSERVE_MR / OBSERVE_MR_FILTER_NG / OBSERVE_MR_TRIGGER` の件数、`mr_rank` 分布、`mr_paper_entries_total`

集計:
```bash
python3 tools/mr_observe_summary.py --day8 20260409
python3 tools/mr_observe_summary.py --print-json
python3 tools/mr_observe_summary.py --multi-day --lookback-days 7 --min-days 3 --min-rank-a 10 --min-rank-a-trigger 5
```

## 5. AI学習を安全に賢くする設定（推奨）
以下は `CONTROL.csv`（本番）側の推奨値です。

```text
ai_auto_train_enabled=1
ai_train_live_only=0
ai_train_include_shadow=1
ai_train_live_boost=1.00
ai_train_shadow_boost=0.70
ai_train_weekly_feedback_enabled=1
ai_train_weekly_good_hours=10,11,14,15
ai_train_weekly_bad_hours=12,13
ai_train_weekly_good_hour_boost=1.20
ai_train_weekly_bad_hour_penalty=0.70
ai_lot_lock_enabled=1
ai_lot_lock_min_samples=120
ai_lot_lock_max_lot=0.001
ai_monthly_reval_enabled=1
ai_monthly_reval_lookback_days=120
ai_monthly_reval_min_samples=300
ai_monthly_reval_pf_min=1.00
ai_monthly_reval_expectancy_min=0.000
ai_monthly_reval_min_improve=0.000
ai_gate_enabled=1
ai_gate_min_samples=30
ai_gate_expectancy_min=0.0
ai_gate_pf_min=1.05
ai_auto_rollback_enabled=1
ai_auto_rollback_lookback_days=14
ai_auto_rollback_pf_floor=0.95
ai_auto_rollback_expectancy_floor=-0.01
```

ポイント:
- Shadow混合は `ai_train_shadow_boost=0.70` など低めから開始
- Gateで悪い更新をブロック
- Rollbackで悪化時にしきい値を自動復帰
- サンプル不足時は `ai_lot_lock_*` でLIVEロットを据え置き
- 月初の `monthly_reval` で、長期lookbackを使って閾値を再評価

### 5-1. 過去OHLCVから仮想学習データを作る（BACKTEST）
5年/10年分のチャートCSVから、仮想ENTRY/EXIT結果を `ai_training_log` 互換で生成できます。

OHLCVが手元にない場合（無料・公開データ）:

まず短期間で疎通確認（数十秒）:
```bash
python3 tools/fetch_binance_ohlcv.py \
  --symbol BTCUSDT \
  --interval 5m \
  --start 2026-01-01 \
  --end 2026-02-01 \
  --out ../logs/backtest/ohlcv_test_5m.csv \
  --progress-every 5
```

本番の長期間取得（進捗表示あり）:
```bash
python3 tools/fetch_binance_ohlcv.py \
  --symbol BTCUSDT \
  --interval 5m \
  --start 2021-01-01 \
  --end 2026-01-01 \
  --out ../logs/backtest/ohlcv_binance_btcusdt_5m.csv \
  --progress-every 20
```

そのOHLCVを使って学習データ生成:

```bash
python3 tools/backfill_ai_from_ohlcv.py \
  --ohlcv ../logs/backtest/ohlcv_binance_btcusdt_5m.csv \
  --out ../logs/backtest/ai_training_log_backtest.csv \
  --strategy all \
  --append

# 改善候補（逆張り版も比較生成）
python3 tools/backfill_ai_from_ohlcv.py \
  --ohlcv ../logs/backtest/ohlcv_binance_btcusdt_5m.csv \
  --out ../logs/backtest/ai_training_log_backtest.csv \
  --strategy all_contra \
  --append

# 条件探索グリッド（PF/Expectancy基準）でフィルタ最適化
# 通過候補があればその候補を出力、無ければ安全に元データのまま
python3 tools/backfill_ai_from_ohlcv.py \
  --ohlcv ../logs/backtest/ohlcv_binance_btcusdt_5m.csv \
  --out ../logs/backtest/ai_training_log_backtest_opt.csv \
  --strategy all_plus \
  --optimize-filters \
  --opt-target-pf 1.05 \
  --opt-target-exp 0.0 \
  --opt-min-trades 500 \
  --opt-topk 10 \
  --opt-report ../logs/backtest/backfill_opt_report.json

# 目標未達でも「ベスト候補」を強制採用したい場合のみ（通常は非推奨）
# 末尾に --opt-apply-best-on-fail を追加
```

CONTROLで有効化（最初は弱い重み推奨）:

```text
ai_train_include_backtest=1
ai_train_backtest_boost=0.30
ai_train_backtest_path=../logs/backtest/ai_training_log_backtest.csv
ai_train_backtest_gate_enabled=1
ai_train_backtest_gate_min_samples=300
ai_train_backtest_gate_expectancy_min=0.000
ai_train_backtest_gate_pf_min=1.00
ai_train_backtest_max_rows=3000
```

安全運用の目安:
- `ai_train_backtest_boost` は `0.20〜0.40` から開始
- `ai_train_backtest_gate_enabled=1` のまま使う（基準未達データを自動除外）
- `ai_train_live_only=1` の場合はBACKTESTは学習対象外

## 6. KeychainにAPIキーを安全登録
CLI引数に平文を残さず登録します。

```bash
./tools/register_bitflyer_keychain.sh
python3 tools/live_preflight.py
```

Cloud/Linux（systemd）での安全登録:
```bash
sudo ./tools/register_cloud_secrets_env.sh /etc/ouroboros/secrets.env
python3 tools/live_preflight.py
```

## 7. 常駐化（再起動復旧）
### dashboard + ngrok
```bash
./tools/install_dashboard_launchagent.sh
./tools/uninstall_dashboard_launchagent.sh
launchctl print gui/$(id -u)/com.ouroboros.dashboard.ngrok
```

### notifier
```bash
./tools/install_trade_notifier_launchagent.sh
./tools/uninstall_trade_notifier_launchagent.sh
launchctl print gui/$(id -u)/com.ouroboros.trade.notifier
```

### Cloud/Linux (systemd) の健全性確認
```bash
./tools/cloud_systemd_healthcheck.sh
# ngrok常駐も確認
./tools/cloud_systemd_healthcheck.sh --include-ngrok
# shadow常駐も確認
./tools/cloud_systemd_healthcheck.sh --include-shadow
# MR observe 常駐も確認
./tools/cloud_systemd_healthcheck.sh --include-mr-observe
# notifier常駐も確認
./tools/cloud_systemd_healthcheck.sh --include-trade-notifier
# weekly autotrain常駐も確認
./tools/cloud_systemd_healthcheck.sh --include-weekly-autotrain
# daily autotrain常駐も確認
./tools/cloud_systemd_healthcheck.sh --include-daily-autotrain
# champion gate常駐も確認
./tools/cloud_systemd_healthcheck.sh --include-champion-gate
# champion rollback常駐も確認
./tools/cloud_systemd_healthcheck.sh --include-champion-rollback
# drift watch常駐も確認
./tools/cloud_systemd_healthcheck.sh --include-drift-watch
# API接続まで含めて確認
./tools/cloud_systemd_healthcheck.sh --run-preflight
# ngrok + API接続を同時確認
./tools/cloud_systemd_healthcheck.sh --include-ngrok --run-preflight
# shadow + API接続を同時確認
./tools/cloud_systemd_healthcheck.sh --include-shadow --run-preflight
# MR observe + API接続を同時確認
./tools/cloud_systemd_healthcheck.sh --include-mr-observe --run-preflight
# ngrok + notifier + API接続を同時確認
./tools/cloud_systemd_healthcheck.sh --include-ngrok --include-trade-notifier --run-preflight
# ngrok + notifier + weekly autotrain + API接続を同時確認
./tools/cloud_systemd_healthcheck.sh --include-ngrok --include-trade-notifier --include-weekly-autotrain --run-preflight
# ngrok + notifier + weekly + daily autotrain + API接続を同時確認
./tools/cloud_systemd_healthcheck.sh --include-ngrok --include-trade-notifier --include-weekly-autotrain --include-daily-autotrain --run-preflight
# ngrok + notifier + weekly + daily + champion gate + API接続を同時確認
./tools/cloud_systemd_healthcheck.sh --include-ngrok --include-trade-notifier --include-weekly-autotrain --include-daily-autotrain --include-champion-gate --run-preflight
# ngrok + notifier + weekly + daily + champion gate + champion rollback + API接続を同時確認
./tools/cloud_systemd_healthcheck.sh --include-ngrok --include-trade-notifier --include-weekly-autotrain --include-daily-autotrain --include-champion-gate --include-champion-rollback --run-preflight
# ngrok + notifier + weekly + daily + champion gate + champion rollback + drift watch + API接続を同時確認
./tools/cloud_systemd_healthcheck.sh --include-ngrok --include-trade-notifier --include-weekly-autotrain --include-daily-autotrain --include-champion-gate --include-champion-rollback --include-drift-watch --run-preflight
```

### Cloud/Linux (systemd) でShadow常駐を後から有効化
```bash
./tools/install_systemd_services.sh --with-shadow
sudo systemctl status ouroboros-shadow.service --no-pager -l
tail -n 120 run_shadow.log
ls -lt ../logs/instances/shadow/trade_log_*.csv | head
```

### Cloud/Linux (systemd) でMR observe常駐を後から有効化
```bash
./tools/install_systemd_services.sh --with-mr-observe
sudo systemctl status ouroboros-mr-observe.service --no-pager -l
tail -n 120 run_mr_observe.log
ls -lt ../logs/instances/mr_observe/trade_log_*.csv | head
```

### Cloud/Linux (systemd) でngrok常駐を後から有効化
```bash
./tools/install_systemd_services.sh --with-ngrok
sudo systemctl status ouroboros-ngrok.service --no-pager -l
```

### Cloud/Linux (systemd) で取引通知notifier常駐を後から有効化
```bash
./tools/install_systemd_services.sh --with-trade-notifier
sudo systemctl status ouroboros-trade-notifier.timer --no-pager -l
sudo journalctl -u ouroboros-trade-notifier.service -n 80 --no-pager
```

### Cloud/Linux (systemd) で週次レポート→AI学習反映を常駐化
```bash
./tools/install_systemd_services.sh --with-weekly-autotrain
sudo systemctl status ouroboros-weekly-autotrain.timer --no-pager -l
sudo journalctl -u ouroboros-weekly-autotrain.service -n 80 --no-pager
```

### Cloud/Linux (systemd) で日次再学習トリガーを常駐化
```bash
./tools/install_systemd_services.sh --with-daily-autotrain
sudo systemctl status ouroboros-daily-autotrain.timer --no-pager -l
sudo journalctl -u ouroboros-daily-autotrain.service -n 80 --no-pager
```

### Cloud/Linux (systemd) でChampion/Challenger昇格判定を常駐化
```bash
./tools/install_systemd_services.sh --with-champion-gate
sudo systemctl status ouroboros-champion-gate.timer --no-pager -l
sudo journalctl -u ouroboros-champion-gate.service -n 80 --no-pager
```

### Cloud/Linux (systemd) でChampionロールバック監視を常駐化
```bash
./tools/install_systemd_services.sh --with-champion-rollback
sudo systemctl status ouroboros-champion-rollback.timer --no-pager -l
sudo journalctl -u ouroboros-champion-rollback.service -n 80 --no-pager
```

### Cloud/Linux (systemd) でドリフト監視を常駐化
```bash
./tools/install_systemd_services.sh --with-drift-watch
sudo systemctl status ouroboros-drift-watch.timer --no-pager -l
sudo journalctl -u ouroboros-drift-watch.service -n 80 --no-pager

# 30分ごと実行の予定確認
systemctl list-timers --all | grep ouroboros-drift-watch
```

### Cloud/Linux (systemd) で朝の自動再開チェックを常駐化
```bash
./tools/install_systemd_services.sh --with-morning-start-check
sudo systemctl status ouroboros-morning-start-check.timer --no-pager -l
sudo journalctl -u ouroboros-morning-start-check.service -n 80 --no-pager
```

挙動:
- 15分ごとに実行
- `start_hour` の20分前〜5分後だけ判定
- 条件を満たせば `today_on=1` と `trade_enabled=1` を戻す
- `ouroboros-bot.service` が止まっていれば起動
- 条件未達なら通知だけ出して再開しない

### Cloud/Linux (systemd) のunit更新を反映（run.log追記など）
```bash
./tools/install_systemd_services.sh --with-ngrok
sudo systemctl restart ouroboros-bot.service ouroboros-dashboard.service ouroboros-ngrok.service
```

shadowを含める場合:
```bash
./tools/install_systemd_services.sh --with-shadow
sudo systemctl restart ouroboros-bot.service ouroboros-dashboard.service ouroboros-shadow.service
```

`bot.py` / `run.py` を差し替えた日も、shadow は long-running なので `ouroboros-shadow.service` を明示的に再起動する:
```bash
sudo systemctl restart ouroboros-bot.service ouroboros-shadow.service
```

notifierを含める場合:
```bash
./tools/install_systemd_services.sh --with-ngrok --with-trade-notifier
sudo systemctl restart ouroboros-bot.service ouroboros-dashboard.service ouroboros-ngrok.service ouroboros-trade-notifier.timer
```

notifier + weekly autotrain を含める場合:
```bash
./tools/install_systemd_services.sh --with-ngrok --with-trade-notifier --with-weekly-autotrain
sudo systemctl restart ouroboros-bot.service ouroboros-dashboard.service ouroboros-ngrok.service ouroboros-trade-notifier.timer ouroboros-weekly-autotrain.timer
```

notifier + weekly + daily autotrain を含める場合:
```bash
./tools/install_systemd_services.sh --with-ngrok --with-trade-notifier --with-weekly-autotrain --with-daily-autotrain
sudo systemctl restart ouroboros-bot.service ouroboros-dashboard.service ouroboros-ngrok.service ouroboros-trade-notifier.timer ouroboros-weekly-autotrain.timer ouroboros-daily-autotrain.timer
```

notifier + weekly + daily + champion gate を含める場合:
```bash
./tools/install_systemd_services.sh --with-ngrok --with-trade-notifier --with-weekly-autotrain --with-daily-autotrain --with-champion-gate
sudo systemctl restart ouroboros-bot.service ouroboros-dashboard.service ouroboros-ngrok.service ouroboros-trade-notifier.timer ouroboros-weekly-autotrain.timer ouroboros-daily-autotrain.timer ouroboros-champion-gate.timer
```

notifier + weekly + daily + champion gate + champion rollback を含める場合:
```bash
./tools/install_systemd_services.sh --with-ngrok --with-trade-notifier --with-weekly-autotrain --with-daily-autotrain --with-champion-gate --with-champion-rollback
sudo systemctl restart ouroboros-bot.service ouroboros-dashboard.service ouroboros-ngrok.service ouroboros-trade-notifier.timer ouroboros-weekly-autotrain.timer ouroboros-daily-autotrain.timer ouroboros-champion-gate.timer ouroboros-champion-rollback.timer
```

notifier + weekly + daily + champion gate + champion rollback + drift watch を含める場合:
```bash
./tools/install_systemd_services.sh --with-ngrok --with-trade-notifier --with-weekly-autotrain --with-daily-autotrain --with-champion-gate --with-champion-rollback --with-drift-watch
sudo systemctl restart ouroboros-bot.service ouroboros-dashboard.service ouroboros-ngrok.service ouroboros-trade-notifier.timer ouroboros-weekly-autotrain.timer ouroboros-daily-autotrain.timer ouroboros-champion-gate.timer ouroboros-champion-rollback.timer ouroboros-drift-watch.timer
```

shadow + notifier + weekly autotrain を含める場合:
```bash
./tools/install_systemd_services.sh --with-shadow --with-trade-notifier --with-weekly-autotrain
sudo systemctl restart ouroboros-bot.service ouroboros-dashboard.service ouroboros-shadow.service ouroboros-trade-notifier.timer ouroboros-weekly-autotrain.timer
```

### Cloud/Linux (systemd) のngrok常駐ログ監視
```bash
# 直近ログ
sudo journalctl -u ouroboros-ngrok.service -n 120 --no-pager

# リアルタイム監視
sudo journalctl -u ouroboros-ngrok.service -f

# URL疎通（VM内）
curl -s http://127.0.0.1:4040/api/tunnels | python3 -m json.tool
```

### Cloud/Linux (systemd) の取引通知notifierログ監視
```bash
# 直近ログ
sudo journalctl -u ouroboros-trade-notifier.service -n 120 --no-pager

# リアルタイム監視
sudo journalctl -u ouroboros-trade-notifier.service -f
```

### Cloud/Linux (systemd) の週次レポート→AI学習反映ログ監視
```bash
# 直近ログ
sudo journalctl -u ouroboros-weekly-autotrain.service -n 120 --no-pager

# 手動1回実行
sudo systemctl start ouroboros-weekly-autotrain.service
```

### Cloud/Linux (systemd) の日次再学習トリガーログ監視
```bash
# 直近ログ
sudo journalctl -u ouroboros-daily-autotrain.service -n 120 --no-pager

# 手動1回実行
sudo systemctl start ouroboros-daily-autotrain.service
```

### Cloud/Linux (systemd) のChampion/Challenger昇格判定ログ監視
```bash
# 直近ログ
sudo journalctl -u ouroboros-champion-gate.service -n 120 --no-pager

# 手動1回実行
sudo systemctl start ouroboros-champion-gate.service
```

### Cloud/Linux (systemd) のChampionロールバック監視ログ監視
```bash
# 直近ログ
sudo journalctl -u ouroboros-champion-rollback.service -n 120 --no-pager

# 手動1回実行
sudo systemctl start ouroboros-champion-rollback.service
```

### Cloud/Linux (systemd) のドリフト監視ログ監視
```bash
# 直近ログ
sudo journalctl -u ouroboros-drift-watch.service -n 120 --no-pager

# 手動1回実行
sudo systemctl start ouroboros-drift-watch.service
```

## 8. よく使うログ確認
```bash
tail -n 120 run.log
tail -n 120 run_shadow.log
tail -n 120 ci_logs/dashboard_ngrok_wrapper.log
tail -n 120 ci_logs/launchd_dashboard_out.log
tail -n 120 ci_logs/launchd_dashboard_err.log
tail -n 120 ci_logs/launchd_trade_notifier_out.log
tail -n 120 ci_logs/launchd_trade_notifier_err.log
```

## 9. トラブル時の定型対応
### ngrokがoffline（ERR_NGROK_3200 等）
```bash
pkill -f ngrok || true
./tools/start_dashboard_ngrok.sh
```

### dashboard常駐を入れ直す
```bash
./tools/uninstall_dashboard_launchagent.sh
pkill -f ngrok || true
./tools/install_dashboard_launchagent.sh
```

### stale lockを消したい
ダッシュボードの `ホーム` / `Shadow起動/停止` にある
`stale .run_lock クリア` を優先。  
CLI手動削除は最終手段。

## 10. 手動でrun.pyを回す（デバッグ用途）
通常はダッシュボード起動/停止、または `safe_start_bot.sh`/`safe_stop_bot.sh` を推奨。  
デバッグ時のみ直接実行します。

```bash
python3 run.py --interval 300 --print-tick
```

## 11. 認証ユーザー管理
```bash
python3 tools/create_dashboard_user.py --username <your_name>
```

## 12. 変更時の記録
`⚙️ Bot設定` 保存時は変更履歴へ自動記録されます。  
履歴書き込みに失敗した場合は保存を自動ロールバックします（未記録のまま反映しない）。  
追加メモは `🛠 ツール・メンテナンス` の `🧾 バージョン・変更履歴` から手動記録します。

## 13. git commit時に履歴を自動記録
`dashboard_change_log.jsonl` へ、commit単位の履歴を自動追記します。

```bash
./tools/install_git_post_commit_hook.sh
```

一時的に無効化:
```bash
OUROBOROS_AUTO_CHANGELOG=0 git commit -m "..."
```

解除:
```bash
./tools/uninstall_git_post_commit_hook.sh
```

## 14. ダッシュボード軽量モード（重い描画を手動実行）
`Sidebar -> パフォーマンス -> 描画モード` で切替できます。

- `標準（normal）`: すべて自動描画
- `軽量（lite）`: Analytics / pos_id 詳細チャートは `実行` ボタン押下時のみ描画

補足:
- 設定は `ui_config.json` に保存されるため再起動後も維持されます。
- 軽量モード時、対象期間や `pos_id` が変わると再度 `実行` が必要です。

## 15. Streamlit互換ガード（将来エラー予防）
`ci_check.py` に UI 互換チェックを追加済みです。  
`dashboard.py` / `keiba_dashboard.py` に `use_container_width` が混入した場合、CIで失敗させます。

```bash
cd ~/trading_bot/MAIN
python3 ci_check.py
```

## 16. Live Trading Desk（全タブ共通ヘッダー）
全タブ上部に、運用状態を1画面で確認できる `Live Trading Desk` ストリップを表示します。

- 表示内容: `DRIFT状態 / TRADE ON-OFF / AUTO TRAIN / RUN LOCK / PF / 勝率 / AvgRet / サンプル数`
- `DRIFT ALERT` 時は状態バッジが自動で警戒色になります。
- Homeタブの「マーケット・パルス」と併用して、全体監視と詳細監視を分離できます。

## 17. Home強化（トレード実感UI）
`🏠 ホーム・稼働状況` に、運用判断を速める5機能を追加しました。

- `約定テープ`: 直近の 新規/決済/強制エグジット をテープ表示
- `セッション損益ラダー`: 時間帯ごとの損益（推定）と累積推移
- `リスク予算ゲージ`: `daily_loss_limit_pct` に対する損失消費率
- `ドリフト復帰タイムライン`: 復帰までの進捗（サンプル/連続NORMAL/カナリー/自動復帰）
- `ワンクリック再現（負けトレード）`: 負けトレードを1クリックで再現表示 + `pos_id`/履歴タブへジャンプ
