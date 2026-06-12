# IBKR サブエージェント スペック表

> 更新日: 2026-06-11  
> 対象: `MAIN/tools/ibkr_*.{py,sh}` + LaunchAgent plist群 + `ibkr_bot.py` / `investor_council.py`  
> 目的: 各エージェントの役割・入出力・スケジュールを定義し、将来の変更時の整合性チェックに使う  
> 実装バージョン: `ibkr_bot.py=v2026.06.12.1`（**ドンチャン・ブレイクアウトobserve追加**: `ibkr_donchian_observe_n=250`[1分足250本=5分足N=50等価・検証5で全戦略中最強+164.50%/WF両期間プラス]。記録のみ＝実取引・SMA経路に無影響。`DONCHIAN_OBSERVE`ログでシグナル頻度・SMA一致率・約定品質を実環境観測→採用判断。cooldown=30分/symbol×side。旧v2026.06.11.4: C:通知堅牢化 / B:ATR-SL有効化済[sl=2.0/tp=4.0] / A:SELL対称ガード observe / P2a:ATR下限 observe[0.20] / P2b:トレンド整合 observe[250]。Phase2: `/protrader`。土台: `MAIN/docs/trading_knowledge/`9本+バックテスト基盤[検証1-5]）  
> 旧: v2026.06.07.1（投資円卓会議統合 + 経済イベントゲート observe先行）

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
| **主要変数** | `VM_HOST=161.33.26.35`, `VM_USER=ubuntu`, `VM_KEY=/Users/tani/.ssh/ouroboros_vm_key` |
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
| **LLM** | Ollama `qwen2.5:0.5b` @ `http://127.0.0.1:11434`（VM local）。1.5b→0.5bへ変更+ウォームアップ+timeout420s+num_predict=256上限（2026-06-12: 1.5bはVMのCPUで240s超応答不能、さらに取引時間帯のCPU競合下では生成無制限だと300s超のため生成上限化。取引時間帯の実条件で実走検証済み） |
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
| **LLM** | Ollama `qwen2.5:0.5b` @ `http://127.0.0.1:11434`（VM local）。1.5b→0.5bへ変更+ウォームアップ+timeout420s+num_predict=256上限（2026-06-12: 1.5bはVMのCPUで240s超応答不能、さらに取引時間帯のCPU競合下では生成無制限だと300s超のため生成上限化。取引時間帯の実条件で実走検証済み） |
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
VM_KEY  = /Users/tani/.ssh/ouroboros_vm_key
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
- **Ollama**: `http://127.0.0.1:11434` (VM local)、モデル `qwen2.5:0.5b` インストール済みであること（2026-06-12に1.5b→0.5bへ変更）
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

## 投資円卓会議（Investment Council / 2026-06-04 LIVE / ibkr_bot v2026.06.04.1）

> note記事「実在投資家11人の思想トレース」ベースのALL-YESゲート。実装は `investor_council.py`（436行）、`ibkr_bot.py` から `ibkr_council_enabled=1` で起動。詳細スキルは `/council`。

| パラメータ（IBKR_CONTROL.csv） | 値 | 意味 |
|---|---|---|
| `ibkr_council_enabled` | 1 | 円卓会議ゲート有効（**LIVE稼働中**） |
| `ibkr_council_min_conviction` | 2.5 | 最低確信度スコア |
| `ibkr_council_require_core_setup` | 1 | コアセットアップ必須 |
| `ibkr_council_min_rr` | 2.0 | 最低リスクリワード比 |
| `ibkr_council_overextended_pct` | 3.0 | 過伸長ブロック閾値（%） |
| `ibkr_council_vertical_pct` | 4.0 | 垂直上昇ブロック閾値（%） |
| `ibkr_council_counter_trend_daily_pct` | 0.8 | 逆張り遮断の日次変動閾値（%） |
| `ibkr_council_open_skip_min` | 15 | 寄り後スキップ分数 |
| `ibkr_council_weekly_dd_stop_usd` | -12.0 | 週次DDストップ（$） |
| `ibkr_council_weekly_target_usd` | 0.0 | 週次目標（$・0=無効） |

挙動: `COUNCIL_BLOCK`（逆張り等を遮断）/ 承認時のみエントリー。週次DD固定で `weekly_dd_stop_usd` 到達時は週内停止。

## コツコツドカン対策（2026-06-04）

| パラメータ（IBKR_CONTROL.csv） | 値 | 意味 |
|---|---|---|
| `ibkr_streak_stop_max_losses` | 2 | 連敗ストップ数（2連敗で当日エントリー停止） |
| `ibkr_weekly_loss_limit_usd` | -80 | 週次損失上限（$） |

## 監視銘柄・銘柄選定（2026-06-04 拡張）

- `ibkr_monitor_symbols`: **40銘柄**（旧20→拡張）。テック中心に高配当/ディフェンシブ（XOM,CVX,OXY,UNH,LLY,JNJ,ABBV,COST,WMT,PG,CAT,RTX,DE,FCX,NEM,BAC,V,MA,NEE,AMT,BKNG）を追加。
- `ibkr_symbol_select_mode=momentum` / `ibkr_symbol_select_top_n=8`: モメンタム上位8銘柄を毎ループ選定。

## 現行キーパラメータ（IBKR_CONTROL.csv / VM=正本 2026-06-07時点）

| パラメータ | 値 | 備考 |
|---|---|---|
| `ibkr_port` | 7496 | **LIVE port** |
| `ibkr_trade_symbol` | QQQ | 基準銘柄 |
| `ibkr_shares` | 1 | 1注文株数 |
| `ibkr_tp_pct` / `ibkr_sl_pct` | 1.0 / -0.5 | R:R 2:1（2026-05-24 拡大） |
| `ibkr_daily_loss_limit_usd` | -20 | 日次損失上限 |
| `ibkr_max_trades_per_day` | 6 | 1日最大取引数 |
| `ibkr_max_concurrent_positions` | 2 | 同時建玉上限 |
| `ibkr_vix_block_threshold` | 30 | VIXゲート |
| `ibkr_start_hour_et`–`ibkr_end_hour_et` | 9:45–15:50 ET | 取引時間帯 |
| `ibkr_atr_tp_multiplier` | 1.5 | ATR適応型TP |
| `ibkr_sl_cooldown_min` | 30 | SL後クールダウン |
| `ibkr_chart_ai_enabled` / `ibkr_chart_ai_min_prob` | 1 / 0.80 | Chart AIゲート |

## 経済イベントゲート（2026-06-07 / ibkr_bot v2026.06.07.1 / observe先行）

> FOMC/CPI/PCE/雇用統計など予定された高ボラ発表の前後でエントリーを回避（米株一次情報記事の発想をリスクフィルタ化）。BTCの`SKIP_NEWS`相当がIBKRに無かった穴を塞ぐ。VIXゲートと同じグローバル位置に設置。

| パラメータ（IBKR_CONTROL.csv） | 値 | 意味 |
|---|---|---|
| `ibkr_econ_gate_enabled` | 1 | 経済イベントゲート有効 |
| `ibkr_econ_gate_mode` | observe | observe=記録のみ(実取引不変) / block=実遮断（検証後に切替予定） |
| `ibkr_econ_gate_before_min` | 15 | 発表の何分前から窓に入れるか |
| `ibkr_econ_gate_after_min` | 60 | 発表の何分後まで窓を継続（CPIスパイク+FOMC会見をカバー） |
| `ibkr_econ_gate_events` | "YYYY-MM-DD HH:MM;…" | 発表日時(ET基準)をセミコロン区切り。過去日程は自動無効化。**実日程はBLS/Fed公式から手入力** |

実装: `_econ_event_gate(ctrl, now_et)` がイベント窓内を判定。`VIX_BLOCK`の直後に設置し、observe=`OBSERVE_ECON_WOULD_BLOCK`をCSV記録して継続 / block=`ECON_BLOCK`で`_early_exit`遮断。
初期投入日程(検証済): CPI 2026-06-10 08:30 / FOMC声明 2026-06-17・07-29 14:00（[Fed](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) / [BLS](https://www.bls.gov/schedule/news_release/cpi.htm)）。
運用: observe先行→would_block発生と損益相関を検証→block化はたにさん承認後。データ源を将来API化する場合は別途。

## IB Gateway 2FA運用（2026-06-08 改訂）

> 課題: IBKRの2FAは本来「週1回」(日曜01:00 ET以降の初回ログイン)で済む([IBC公式](https://github.com/IbcAlpha/IBC/blob/master/userguide.md))が、Gatewayが週途中でセッションを失い深夜にcold再ログイン→2FAプッシュ→就寝中で承認できず失敗、を繰り返していた。US市場 22:30–05:00 JST=日本の深夜なのが構造要因。autologin.log上、成功はしばしば05:27(=US閉場後)で**場中ダウン**していた。

| 項目 | 設定 | 意図 |
|---|---|---|
| `ouroboros-ibkr-2fa-reminder.timer` | **20:45 JST** (13:15→21:15→20:45) | 寄り前にタニへ2FAリマインド(ログイン5分前) |
| `ouroboros-ibgateway.timer` | **20:50 JST** (13:20→21:20→20:50) | 寄り前にcoldログイン→タニが2FA承認→場中セッション維持 |
| `ouroboros-ibgateway-retry.timer` (drop-in) | 15,17,19,21,23,**01**,05:20 (2026-06-10: 01:20を復活/03:20は除外) | 落ちた時の再ログイン試行(健全時はno-op)。場中復旧のため深夜01:20を戻した |
| `ouroboros-ibkr-gateway-down-alert.timer` (新規 2026-06-10) | 10分毎 | **US場中(ET平日09:30-16:00)にport7496が閉じたらntfy通知**(`tools/ibkr_gateway_down_alert.sh`・30分dedup)。場中ダウンに気づけるように |
| `jts.ini autoRestartTime` | 06:00 JST | US閉場(05:00)直後に自動再起動・セッション保持 |

注意:
- 別端末(スマホIBKRアプリ/Web)で同口座にログインするとGatewayセッションが蹴られ再2FAになる。Gateway稼働中は別端末ログインを避ける。
- 2FAはタップ必須なので**夜間に自動で立て直す方法は無い**(retryを戻しても就寝中はタップ不可)。→ 場中ダウン通知でタニが気づき「起動し直して」で復旧する運用。
- Gateway停止の実態(2026-06-09 23:45は"Deactivated successfully"=クラッシュでなく正常停止。IBKR側ログオフ/別端末ログインの疑い)。根本のセッション維持改善は別途課題。
- 別件修正(2026-06-10): `ouroboros-dashboard.service` が8501ポート競合で約4万回クラッシュループしていたため stop+disable(html/unified dashboardが正常稼働中で冗長)。

## 変更チェックリスト

エージェント関連コードを変更する際は以下を確認すること:

- [ ] `python3 -m py_compile tools/<script>.py` でシンタックスエラーなし
- [ ] 変更したファイルパスがこのスペック表と一致している
- [ ] LaunchAgent plist のパス・引数が変更内容と一致している
- [ ] `--dry-run` / `--no-ntfy` で動作確認済み
- [ ] このスペック表（`docs/IBKR_AGENT_SPEC.md`）を更新済み
- [ ] `OUROBOROS_TRADING_SPEC_TABLE.md` の関連項目を更新済み（必要な場合）
