# IBKR サブエージェント スペック表

> 更新日: 2026-05-08  
> 対象: `MAIN/tools/ibkr_*.{py,sh}` + LaunchAgent plist群  
> 目的: 各エージェントの役割・入出力・スケジュールを定義し、将来の変更時の整合性チェックに使う

---

## アーキテクチャ概要

```
VM (ubuntu@161.33.26.35)
  └── ouroboros-ibkr-bot.service    ← IBKR Paper Trading ボット
        ibkr_trade_log_YYYYMMDD.csv
        ibkr_state.json
        IBKR_CONTROL.csv

         ↕ SSH/scp（ibkr_vm_sync.sh, 5分間隔）

Mac (JST / ローカル)
  ├── .local_llm/ibkr/
  │     ├── logs/ibkr_trade_log_*.csv   ← VM から同期
  │     ├── ibkr_state.json             ← VM から同期
  │     ├── prebrief/
  │     │     ├── prebrief_*.json       ← ibkr_prebrief_agent.py 出力
  │     │     └── prebrief_latest.json
  │     └── review/
  │           ├── review_*.json         ← ibkr_session_review_agent.py 出力
  │           └── review_latest.json
  └── review_out/
        ├── ibkr_vm_sync_status.json    ← vm_sync ステータス
        └── ibkr_gateway_watch_state.json ← gateway_watch ステータス
```

---

## エージェント一覧

### 1. ibkr_vm_sync (ibkr_snapshot LaunchAgent)

| 項目 | 値 |
|------|-----|
| **ファイル** | `tools/ibkr_vm_sync.sh` |
| **LaunchAgent** | `com.ouroboros.ibkr_snapshot` |
| **呼び出し元** | `tools/run_ibkr_snapshot.sh` |
| **スケジュール** | 5分ごと（`StartInterval: 300`） |
| **稼働時間** | JST 22:00–07:00（US市場時間帯のみ）。`--force` で強制実行可 |
| **入力** | VM: `ibkr_state.json`, `IBKR_CONTROL.csv`, `logs/ibkr_trade_log_*.csv` |
| **出力** | `.local_llm/ibkr/ibkr_state.json`, `.local_llm/ibkr/IBKR_CONTROL.csv`, `.local_llm/ibkr/logs/ibkr_trade_log_*.csv`, `review_out/ibkr_vm_sync_status.json` |
| **ログ** | `review_out/ibkr_snapshot_launchd.out.log`, `review_out/ibkr_snapshot_launchd.err.log` |
| **主要変数** | `VM_HOST=161.33.26.35`, `VM_USER=ubuntu`, `VM_KEY=/Users/tani/Downloads/ssh-key-2026-03-04-4.key` |
| **vm_sync_status fields** | `updated_at`, `bot_service` (active\|inactive\|ssh_error), `log_files[]`, `state{}` |

**変更時の注意:**
- VM側のファイルパスが変わる場合は `REMOTE_ROOT` と `LOG_DIR` を更新する
- SSH鍵パスが変わる場合は `VM_KEY` と `ibkr_gateway_watch.py` の `--vm-key` デフォルト値も合わせて変更する

---

### 2. ibkr_gateway_watch

| 項目 | 値 |
|------|-----|
| **ファイル** | `tools/ibkr_gateway_watch.py` |
| **LaunchAgent** | `com.ouroboros.ibkr.gateway.watch` |
| **plist** | `~/Library/LaunchAgents/com.ouroboros.ibkr.gateway.watch.plist` |
| **スケジュール** | 5分ごと（`StartInterval: 300`）、常時稼働 |
| **起動オプション** | `--vm-mode --cooldown-hours 6` |
| **動作** | SSH で VM の `systemctl is-active ouroboros-ibkr-bot.service` を確認。状態変化または cooldown 経過時に ntfy 送信 |
| **入力** | VM SSH, `.local_llm/ibkr/ibkr_state.json`（daily_trade_count, daily_realized_pnl_usd） |
| **出力** | `review_out/ibkr_gateway_watch_state.json` |
| **ログ** | `review_out/ibkr_gateway_watch.launchagent.out.log`, `review_out/ibkr_gateway_watch.launchagent.err.log` |
| **ntfy** | `secrets.toml` の `ntfy_topic_url` / `ntfy_bearer_token` を使用 |
| **gateway_watch_state fields** | `last_issue_key`, `last_status_ok`, `last_checked_at_jst`, `last_reason`, `last_sent_at_jst`, `last_ntfy_result` |

**変更時の注意:**
- VM ホスト/鍵を変更する場合は plist の `--vm-host` / `--vm-key` 引数を更新する
- `--vm-mode` を外すと localhost:7497 チェックモードに戻る（Mac に IB Gateway がある場合のみ有効）
- `cooldown-hours` を変えると通知頻度が変わる

---

### 3. ibkr_prebrief_agent (プリブリーフ)

| 項目 | 値 |
|------|-----|
| **ファイル** | `tools/ibkr_prebrief_agent.py` |
| **LaunchAgent** | `com.ouroboros.ibkr.prebrief` |
| **plist** | `~/Library/LaunchAgents/com.ouroboros.ibkr.prebrief.plist` |
| **スケジュール** | 毎日 22:15 JST（US市場 22:35 開場 20分前） |
| **入力** | `.local_llm/ibkr/logs/ibkr_trade_log_*.csv`（過去14日） |
| **出力** | `.local_llm/ibkr/prebrief/prebrief_YYYYMMDD_HHMMSS.json`, `.local_llm/ibkr/prebrief/prebrief_latest.json` |
| **ログ** | `ci_logs/ibkr_prebrief_out.log`, `ci_logs/ibkr_prebrief_err.log` |
| **LLM** | Ollama `qwen2.5:1.5b` @ `http://127.0.0.1:11434`（Mac local） |
| **ntfy** | 取引データ≥3件: 統計+LLM予測を送信。データ不足: 「データ不足」通知のみ |
| **prebrief JSON fields** | `generated_at`, `lookback_days`, `model`, `trade_count`, `stats_overall`, `llm_text`, `status` |
| **最低取引数** | 3件（`MIN_TRADES = 3`）未満はLLM呼び出しスキップ |

**変更時の注意:**
- モデルを変える場合は `DEFAULT_MODEL` 定数を更新する
- `MAX_CHARS=700` はプロンプト文字数上限（qwen2.5:1.5bのコンテキスト考慮）
- トレードログのカラム名（result, notes等）を変えた場合は `_load_trade_pairs()` を更新する
- 時刻は `hour_et = (hour_utc - 4) % 24` でUTC→ET変換（DST未考慮）
- データ不足でも `prebrief_latest.json` は更新される。HTML dashboard はこの固定名を優先して読む

---

### 4. ibkr_session_review_agent (セッションレビュー)

| 項目 | 値 |
|------|-----|
| **ファイル** | `tools/ibkr_session_review_agent.py` |
| **LaunchAgent** | `com.ouroboros.ibkr.review` |
| **plist** | `~/Library/LaunchAgents/com.ouroboros.ibkr.review.plist` |
| **スケジュール** | 毎日 07:05 JST（US市場 07:00 クローズ後5分） |
| **入力** | `.local_llm/ibkr/logs/ibkr_trade_log_{today}.csv`（当日または前日） |
| **出力** | `.local_llm/ibkr/review/review_YYYYMMDD.json`, `.local_llm/ibkr/review/review_latest.json` |
| **ログ** | `ci_logs/ibkr_review_out.log`, `ci_logs/ibkr_review_err.log` |
| **LLM** | Ollama `qwen2.5:1.5b` @ `http://127.0.0.1:11434`（Mac local） |
| **ntfy** | 取引あり: WR/P&L/内訳+LLMテキスト。取引なし: no trades通知 |
| **review JSON fields** | `generated_at`, `day8`, `summary{n, wr, tp_n, sl_n, timeout_n, total_pnl_usd}`, `llm_text`, `status` |
| **P&L計算** | `entry_price × shares` vs `exit_price × shares`（notesフィールドからパース） |

**変更時の注意:**
- トレードログのカラム名（result, notes等）を変えた場合は `_load_today_session()` を更新する
- JST 07:05 実行だが、US市場は06:59 EST（JST 06:59+14h=20:59 は前日なので実際は当日07:05は翌朝）— 実質「前日US市場の振り返り」
- 取引なしでも `review_latest.json` は更新される。HTML dashboard はこの固定名を優先して読む

---

## 共通事項

### ntfy 設定
- **設定場所**: `MAIN/.streamlit/secrets.toml`
- **必要なキー**: `ntfy_topic_url`, `ntfy_bearer_token`（オプション）
- **現状**: Mac側 `ntfy_topic_url = ""` → 通知未送信。VM側は設定済み

### SSH 接続情報
```
VM_HOST = 161.33.26.35
VM_USER = ubuntu
VM_KEY  = /Users/tani/Downloads/ssh-key-2026-03-04-4.key
```
SSH鍵を変更する場合は以下4箇所を更新:
1. `tools/ibkr_vm_sync.sh` — `VM_KEY`
2. `tools/ibkr_gateway_watch.py` — `--vm-key` デフォルト値
3. `~/Library/LaunchAgents/com.ouroboros.ibkr.gateway.watch.plist` — `--vm-key` 引数（plistに書いていない場合はデフォルト値が使われる）

### LaunchAgent 管理コマンド
```bash
# 状態確認
launchctl list | grep ibkr

# 再起動（plist変更後）
launchctl unload ~/Library/LaunchAgents/com.ouroboros.ibkr.gateway.watch.plist
launchctl load   ~/Library/LaunchAgents/com.ouroboros.ibkr.gateway.watch.plist

# 手動トリガー（テスト用）
/Users/tani/.pyenv/shims/python3 tools/ibkr_gateway_watch.py --vm-mode --dry-run
/Users/tani/.pyenv/shims/python3 tools/ibkr_prebrief_agent.py --no-ntfy
/Users/tani/.pyenv/shims/python3 tools/ibkr_session_review_agent.py --no-ntfy
bash tools/ibkr_vm_sync.sh --force
```

### 依存関係
- **Ollama**: `http://127.0.0.1:11434` (Mac local)、モデル `qwen2.5:1.5b` インストール済みであること
- **Python**: `/Users/tani/.pyenv/shims/python3`（標準ライブラリのみ使用。外部パッケージ不要）
- **SSH**: BatchMode=yes（パスワード入力なし）、鍵ファイルアクセス可能であること
- **Watch判定**: `--vm-mode` では `ouroboros-ibkr-bot.service` と VM内 `127.0.0.1:7497` listen の両方をOK条件とする

### ファイルパス早見表

| ファイル | 用途 |
|---------|------|
| `.local_llm/ibkr/ibkr_state.json` | VMから同期した最新Bot状態 |
| `.local_llm/ibkr/logs/ibkr_trade_log_YYYYMMDD.csv` | VMから同期した取引ログ |
| `.local_llm/ibkr/prebrief/prebrief_YYYYMMDD_HHMMSS.json` | プリブリーフLLM出力 |
| `.local_llm/ibkr/prebrief/prebrief_latest.json` | HTML dashboard 用の固定最新プリブリーフ |
| `.local_llm/ibkr/review/review_YYYYMMDD.json` | セッションレビューLLM出力 |
| `.local_llm/ibkr/review/review_latest.json` | HTML dashboard 用の固定最新レビュー |
| `review_out/ibkr_vm_sync_status.json` | vmSync最終実行状態 |
| `review_out/ibkr_gateway_watch_state.json` | GatewayWatch最終状態 |
| `review_out/ibkr_gateway_watch.launchagent.out.log` | GatewayWatch stdout |
| `review_out/ibkr_snapshot_launchd.out.log` | vmSync stdout |
| `ci_logs/ibkr_prebrief_out.log` | prebrief stdout |
| `ci_logs/ibkr_review_out.log` | review stdout |

---

## 出口ハードニング（2026-06-03 / bot v2026.06.03.1）

> 全17営業日46決済の分析で、損失は「逆張り(-$10.54)」と「翌日持ち越し＋SL逸脱」の2大損(GS -$9.27 SL -0.91%, MSFT -$9.38 TIMEOUT -2.03%)に集中。出口側を補強した。

| 変更 | 内容 | ファイル |
|---|---|---|
| STP対応 | `place_order(order_type="STP", stop_price=...)` を追加（ib_insync `StopOrder`） | `ibkr_adapter.py` |
| 防御逆指値 | エントリー成功時に entry±`sl_pct` のSTPをGTCで即発注。`pos.protective_stop_order_id` / `pos.stop_price` を保持。SL滑り・オーバーナイト窓開けを抑制 | `ibkr_bot.py` 入口 |
| EOD/STALE価格非依存 | 価格取得不可でも EOD(15:55 ET〜)/STALE(前日建玉) は成行で強制クローズ（持ち越しドリフト=MSFT型を遮断） | `ibkr_bot.py` Phase1 |
| 二重約定防止 | ボット自決済時は防御STPを先に `cancel_order`。さらにループ毎にブローカー建玉と照合し、STP約定でポジション消失なら `LIVE_EXIT_STOPFILL` を記録してstate整合 | `ibkr_bot.py` Phase1先頭 |
| 照合の誤発火ガード | ①建玉<90秒はスキップ ②防御STPがオープン注文に残るならスキップ（IB反映遅延での誤消去防止） | `ibkr_bot.py` |

新ログ result: `LIVE_EXIT_STOPFILL`（ブローカー側STP約定の照合記録）。
検証: モックアダプタでSTALE強制クローズ/STOPFILL照合/90秒ガードの3シナリオ合格。MSFT型の-$9.38ドリフトはSTP価格(-$2.31)で確定する想定。

## 変更チェックリスト

エージェント関連コードを変更する際は以下を確認すること:

- [ ] `python3 -m py_compile tools/<script>.py` でシンタックスエラーなし
- [ ] 変更したファイルパスがこのスペック表と一致している
- [ ] LaunchAgent plist のパス・引数が変更内容と一致している
- [ ] `--dry-run` / `--no-ntfy` で動作確認済み
- [ ] このスペック表（`docs/IBKR_AGENT_SPEC.md`）を更新済み
- [ ] `OUROBOROS_TRADING_SPEC_TABLE.md` の関連項目を更新済み（必要な場合）
