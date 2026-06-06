# Ouroboros Handover (Detailed)

最終更新: 2026-05-13 contract-split-stale-review (JST)  
目的: 別トークでも同じ品質で運用・改修を継続できるよう、現状と運用ルールを固定化する。

## 1. まず最重要（事故防止）
- systemdの実体は `./tools/install_systemd_services.sh` 再実行時に `deploy/systemd/*.service|*.timer` から再生成される。
- `tools/*.py` と `deploy/systemd/*.service` の引数がズレると、`unrecognized arguments` で即失敗する。
- `~/trading_bot/MAIN/` 直下に置いた `.py` は、systemd実行対象ではない（`tools/` を使う）。
- Macで `systemctl` は使えない。必ずVMで実行する。

## 2. パスと実行環境

### 2-1. ローカル（Mac）
- ワークスペース: `/Users/tani/trading_bot/trading_bot`
- MAIN: `/Users/tani/trading_bot/trading_bot/MAIN`

### 2-2. VM（Ubuntu）
- ここは再作成で揺れるので、毎回 `pwd` で実パス確認する。
- 既存テンプレートは `install_systemd_services.sh` の `render_unit()` で実行ディレクトリに自動置換される。
- 置換対象（スクリプト内）:
  - `/home/ubuntu/trading_bot/trading_bot/MAIN`
  - `/home/ubuntu/trading_bot/MAIN`

## 3. 現在の主要コンポーネント

### 3-0. バージョン確認の基準
- dashboard 実体: `MAIN/dashboard.py` の `APP_VERSION` を正とする
- widget server 実体: `MAIN/tools/widget_status.py` の `WIDGET_SERVER_VERSION` を正とする
- YT Tool 実体: `python3 yt_tool.py --version` の出力を正とする
- bot logic / 契約の単一起点: `MAIN/ouroboros_contract.py` の `OUROBOROS_BOT_VERSION` / `OUROBOROS_FEATURE_SCHEMA_VERSION` / `TRADE_LOG_FIELDS` / `RESULT_ALLOWED` を正とする
- `MAIN/bot.py` / `MAIN/audit.py` / `MAIN/dashboard.py` / `MAIN/weekly_report.py` は上記 contract を参照する実装に寄せてあり、同種定数を各所で重複定義しない
- MR observe は現在 `phase1.5-a-rank-paper` 扱い。`CONTROL_mr_observe.csv` だけでAランクMRをPAPER検証し、LIVEはしない
- `HANDOVER.json` の `versions` は上記実体に合わせて更新する
- 売買ロジック実装表は `MAIN/docs/OUROBOROS_TRADING_SPEC_TABLE.md` を参照する
- stale運用成果物の棚卸しは `python3 tools/stale_artifact_review.py` を正規コマンドとし、`review_out/stale_artifact_review_latest.json` をダッシュボード・整理判断の基準にする

### 3-0R. 2026-05-13 contract単一起点 / IBKR adapter分離 / stale成果物レビュー
- `MAIN/ouroboros_contract.py` を追加。`OUROBOROS_BOT_VERSION` / `OUROBOROS_FEATURE_SCHEMA_VERSION` / `TRADE_LOG_FIELDS` / `RESULT_ALLOWED` / audit issue builder をここに集約した
- `MAIN/ibkr_adapter.py` は read-only 層として維持し、接続確認・口座情報・価格取得だけを担当する。注文系は `NotImplementedError` で停止する
- `MAIN/ibkr_paper_adapter.py` を追加。paper order 系の `place_order / get_open_orders / get_trades / cancel_order` はこの層だけに残す
- `MAIN/ibkr_bot.py` は `IBKRPaperAdapter` を使う。`test_ibkr_connection.py` や `daily_ops_check.py` などの読み取り専用経路は `IBKRAdapter` を使う
- `MAIN/tools/stale_artifact_review.py` を追加。`stock_shadow_state.json` / `signal_scanner_latest.json` / `ibkr_vm_sync_status.json` / 旧 `trade_system_review_*.json|md` を非破壊で棚卸しし、`STALE / FRESH / ARCHIVE_CANDIDATE` を出す
- `MAIN/tools/archive_stale_artifacts.py` を追加。既定は dry-run で、`stale_artifact_review_latest.json` の `archive_candidates` を plan 化するだけ。`--apply` を付けた時だけ `review_out/archive/legacy_review_*` へ移動する
- `MAIN/tools/ibkr_import_audit.py` を追加。`ibkr_paper_adapter.py` を import してよい呼び出し元を `ibkr_bot.py` に限定し、read-only utility の誤参照を機械チェックする
- この整理では削除や rename はまだしていない。誤認しやすい成果物をまず `latest JSON` で見える化する段階

### 3-0N. 2026-05-14 通知ポリシー共通化の段階導入
- `MAIN/tools/notification_policy.py` を追加。`INFO / WARN / CRITICAL` の正規化、ntfy `Priority` / `Tags`、簡易 cooldown を共通化した
- `trade_event_notifier.py` は既存の event/cooldown ロジックが濃いため、基準実装として維持する
- 先に共通化した通知元:
  - `tools/send_weekly_summary_ntfy.py`
  - `tools/smart_exit_report.py`
  - `signal_scanner_outcome.py`
  - `stock_shadow_weekly.py`
  - `stock_shadow_bot.py`
  - `ibkr_bot.py`
  - `KEIBA/keiba_auto_cycle.py`
- `KEIBA/keiba_public_watch.py` は macOS通知 + ntfy + webhook の複合経路のため、今回は独自実装を維持した
- 2026-05-14 追加: `KEIBA/keiba_public_watch.py` は macOS通知 + webhook を維持しつつ、ntfy だけ `notification_policy.py` に寄せた。event→level は `recovered=INFO`, `url_changed/still_unhealthy=WARN`, `unhealthy=CRITICAL`
- `SPEC_OUROBOROS_NOTIFICATION_WIDGET_V1.md` と `MAIN/docs/notification_routes.md` を正とし、通知経路やレベルを追加した時はこの2ファイルを更新する
- `MAIN/tools/widget_status.py` は 2026-05-14 時点で `/widget-app` / `/widget-app-manifest.json` / `/widget-app-sw.js` を持つ。Scriptable や `/widget-status.json` を壊さず、まずは軽量PWAとしてホーム画面追加できる構成にしている
- `widget-app` は iPhone 向けに下部固定タブ風ナビと `Reflection Snapshot` カードを持ち、オフライン時は最後の取得結果または簡易 offline 状態を返して真っ白表示を避ける
- native shell は `MAIN/widget_native_ios/OuroborosWidgetNative/` に追加。SwiftUI + WKWebView で `Overview / Reflection / Dashboard` を包み、Host と token は app 内 `Settings` タブへ保存する

### 3-0IB2. 2026-05-10 IBKR bot v2026.05.10.1 — VIX filter + 開場待機延長

#### 実装内容（PDFコンセプト取り込み）

**VIX filter（PDF1「米国株朝刊の読み方」— VIX恐怖指数ゲート）**
- `_fetch_vix(state)` 関数追加: Yahoo Finance `query1.finance.yahoo.com/v8/finance/chart/%5EVIX` から取得
- 30分キャッシュ（state: `_vix_value`, `_vix_fetched_ts`）
- API失敗時は前回キャッシュにフォールバック
- `ibkr_vix_block_threshold=28`: VIX ≥ 28 のときエントリーブロック（`result=VIX_BLOCK` としてログ記録）
- 0 に設定で無効化（デフォルト0、現在28で有効）
- 入場ログの note に `vix=XX.X` を常時記録

**開場後待機延長（PDF3「デイトレで触ってはいけない銘柄」— 寄り付き後15分待つ）**
- `ibkr_start_min_et`: 35 → 45（9:30 ET 開場から15分待機）
- US市場の寄り付き直後（9:30-9:45）は高ボラ + 機関の方向付け期間
- 確認後にエントリーすることで「寄り天」チェイスを回避

**適用しなかったコンセプト（精査結果）**
| コンセプト | 理由 |
|-----------|------|
| 高配当株11基準（PDF2） | 長期ファンダメンタル分析；SMAクロス日中戦略と無縁 |
| 信用買い残チェック（PDF3） | IBKR経由では取得困難；QQQ ETFには適用概念が異なる |
| 決算前回避（PDF3） | QQQ ETFには決算がない；個別株追加時に検討 |
| テック株12銘柄推奨（PDF4） | アナリスト推奨情報；自動売買ロジックに組み込み不可 |

#### 動作確認（2026-05-10）
```
VIX現在値: 17.19（17:25 JST、市場クローズ後）
閾値28未満 → 月曜日の稼働時に通常エントリー判断
ibkr_bot v2026.05.10.1 デプロイ済み
```

### 3-0IB. 2026-05-06 IB Gateway常駐監視（Mac読み取り専用）
- TWSを前面表示し続ける代わりに、IB Gateway Paper + Socket Port 7497 を推奨ランタイムにする。
- `test_ibkr_connection.py` は読み取り専用smokeとして、AAPL/MSFT/NVDA/TSLA/QQQ/SPY と USDJPY を確認し、`review_out/ibkr_connection_YYYYMMDD.json` を保存する。
- `daily_ops_check.py` は `ibkr_log_status` に `runtime_status` / `tws_port_status` / `active_error_*` / `version_consistency` を含める。古い失敗ログは監査用に残すが、接続OK時は `active_error_available=false` として画面・通知では異常扱いしない。
- `ibkr_gateway_watch.py` は注文を出さないwatch専用。`--vm-mode` では `ouroboros-ibkr-bot.service` と VM内 `127.0.0.1:7497` の両方を確認し、serviceはactiveでもAPI portが閉じていれば `port_closed` で WARN にする。復旧時も1回通知する。
- 自動化: `./tools/install_ibkr_gateway_watch_launchagent.sh` は既定で `--vm-mode` を含む5分ごとのMac LaunchAgentを入れる。既存の `install_unified_dashboard_healthcheck_launchagent.sh` は毎朝Daily Opsを保存し、timeoutは15秒に延長済み。
- MacBookを閉じてスリープするとLaunchAgent/IB Gateway/watchは止まる。VM側botは影響を受けないが、Mac側IBKR監視を継続するにはクラムシェル運用またはスリープさせない運用が必要。

### 3-0IC. 2026-05-06 IB Gateway VM移行準備（読み取り専用）
- 目的: Macを閉じてもIBKR監視を継続できるよう、IB GatewayをVM側へ寄せる準備をする。
- `tools/vm_ibkr_gateway_readiness.py` を追加。SSHでVMを読み取り専用確認し、Java / Xvfb/VNC / IB Gateway配置 / 起動プロセス / 7497 listen を `READY_SMOKE / SETUP_NEEDED / BLOCKED` で出す。
- `tools/open_vm_ibkr_tunnel.sh` を追加。IB Gatewayの7497は公開せず、`127.0.0.1:17497 -> VM 127.0.0.1:7497` のSSHトンネルで読み取り専用smokeを行う。
- 安全境界: package installなし、service startなし、public port openなし、secret表示なし、注文なし。
- 次段階は、readiness結果が `SETUP_NEEDED` ならVMにJava + headless GUI + 初回ログイン用VNCを入れる。`READY_SMOKE` ならSSHトンネル経由で `test_ibkr_connection.py --host 127.0.0.1 --port 17497` を実行する。
- 2026-05-06 23:23 JST の実VM読み取り専用チェック結果: `READY_SMOKE`。VM側で `IB Gateway` が起動し、`*:7497` がlisten。Mac側SSHトンネル `127.0.0.1:17497 -> VM:7497` 経由のsmokeログも成功済み。
- `daily_ops_check.py` / `ibkr_gateway_watch.py` / unified dashboard は VM正準モードに対応済み。`api_mode=vm_tunnel` でも `effective_port_status=vm:127.0.0.1:7497`、`effective_runtime_status=VM IB Gateway`、`vm_readiness` を優先し、Mac側の `ib_insync` や `127.0.0.1:7497/17497` 失敗は参考情報として残しつつ `active_error` では過剰に前面表示しない。
- 追加確認コマンド: `python3 tools/vm_ibkr_gateway_readiness.py --host 161.33.26.35 --key /Users/tani/Downloads/ssh-key-2026-03-04-4.key --timeout-sec 8 --print-json`、`python3 test_ibkr_connection.py --host 127.0.0.1 --port 17497 --client-id 11 --stocks AAPL,MSFT,NVDA,TSLA,QQQ,SPY --fx USDJPY`。

### 3-0ID. 2026-05-06 VM dashboard / IBKR監視常駐化
- `tools/deploy_vm_dashboard_ops.sh` を追加。VMへ unified dashboard配信、IBKR read-only smoke、Daily Ops更新、IBKR watchdog の systemd unit/timer を配置する。
- VM systemd:
  - `ouroboros-unified-dashboard.service`: `/home/ubuntu/trading_bot/MAIN` を `0.0.0.0:8793` で静的配信。
  - `ouroboros-ibkr-readonly-smoke.timer`: 15分ごとに `test_ibkr_connection.py --host 127.0.0.1 --port 7497 --client-id 11` を実行。
  - `ouroboros-daily-ops-check.timer`: 5分ごとに `daily_ops_check.py --url http://127.0.0.1:8793/tools/unified_dashboard.html` を実行。
  - `ouroboros-ibkr-gateway-watch.timer`: 5分ごとにwatchを実行し、異常/復旧通知を重複抑制。
- 2026-05-06 23:35 JST 確認: VM内 `dashboard_ok=True`, `ibkr_connected=True`, `needs_smoke=False`, `next_action=OK`, `version_consistency=OK`, `watch=OK`。
- 2026-05-07 05:34 JST 確認: VM内 `ibkr_connected=True`, `effective_port_status.open=True`, `watch_ok=True`, `watch_ntfy=HTTP 200`。古い `ibkr_connection_error_YYYYMMDD.json` は監査用に残るが、`active_error_available=false` なら現行障害ではない。
- 注意: VM上では `127.0.0.1:7497` を直接使うため、Mac側 `17497` SSHトンネルは不要。ただしMacからVM IBKRを読む時だけ `17497 -> VM:7497` トンネルを使う。IB Gateway画面共有/VNCはログイン・設定変更時だけ必要で、通常監視には不要。

### 3-0IE. 2026-05-07 VM Tailscale
- VMにTailscale `1.96.4` を導入し、Tailnet参加済み。
- VM Tailscale IP: `100.66.216.5`
- iPhone固定URL: `http://100.66.216.5:8793/tools/unified_dashboard.html`
- 2026-05-07 確認: VM側 `tailscale status=Running`、`tailscale ip -4=100.66.216.5`、VM内 `http://100.66.216.5:8793/tools/unified_dashboard.html` は `HTTP/1.0 200 OK`。
- Mac側Tailscaleが未接続の場合、Macから `100.66.216.5:8793` は疎通しない。iPhone側でTailscaleをONにして同URLを開く。

### 3-0IF. 2026-05-07 VM KEIBA常駐化
- `KEIBA/` をVM `/home/ubuntu/trading_bot/KEIBA` へ同期。
- VMに `streamlit` / `scikit-learn` をユーザー環境へ追加。
- systemd:
  - `ouroboros-keiba-streamlit.service`: Streamlit app を `0.0.0.0:8511` で常駐。
  - `ouroboros-keiba-status-server.service`: `keiba_status_server.py` を `0.0.0.0:8789` で常駐。`KEIBA_ACTIONS_DISABLED=1` で外部POST操作は無効化。
- iPhone / Tailscale:
  - KEIBA app: `http://100.66.216.5:8511`
  - KEIBA status: `http://100.66.216.5:8789/keiba-status.json`
  - unified dashboard: `http://100.66.216.5:8793/tools/unified_dashboard.html`
- unified dashboard はVM Tailscale上で開いた時だけ、KEIBA Status URLを `http://100.66.216.5:8789/keiba-status.json` へ自動補正する。
- 2026-05-07 17:56 JST 確認: `8511/_stcore/health=ok`, `8789/health={"ok":true}`, 両service active。

### 3-0A. 2026-04-17 追加済みロジック
- bot logic: `2026.05.05.3`
- feature schema: `ohlc-chart-pattern-quality-market-phase-transition-near-tp-aiba-phase-fallback-mfe-mae-fib-elliott-v1`
- 5分OHLCを `ltp` から内部生成し、`state._ohlc_current` / `state.ohlc_history` に保存する
- OHLC各足に `ticks` を持たせ、`chart_pattern_min_bar_ticks` / `chart_pattern_quality_lookback_bars` で品質判定する
- `cp_quality=OK` のチャートパターンだけAI scoreへ反映し、`THIN` はログ記録のみで昇格判断に使わない
- 対象パターンは `DOUBLE_TOP` / `DOUBLE_BOTTOM` / `HEAD_AND_SHOULDERS`
- note は `cp_name` / `cp_stage` / `cp_bias` / `cp_confirmed` / `cp_trend` / `cp_neckline` / `cp_quality` / `cp_avg_ticks` を持つ
- A/B/C局面判定を追加。`phase=A` は下落、`phase=B` は横ばい、`phase=C` は上昇として note に残す
- B局面の強制ブロックは既定OFF。`market_phase_block_b_enabled=1` の時だけ `OBSERVE_PHASE_B` でentryを止める

### 3-0B2. 2026-04-29 MR AランクPAPER昇格
- `CONTROL_mr_observe.csv` に `mr_paper_enabled=1`, `mr_paper_min_rank=A`, `mr_paper_require_trigger=1`, `mr_paper_require_reclaim=1` を追加。
- 対象は `OUROBOROS_INSTANCE=mr_observe` の専用runnerのみ。
- `paper_mode=1 / live_enabled=0 / observe_only=1` を維持し、main/shadowの発注ロジックには混ぜない。
- 昇格条件は `OBSERVE_MR_TRIGGER` かつ `mr_rank=A` かつ `mr_reclaim=1`。
- entry note に `mr_paper=1 strategy=MR mr_rank=...` を残し、`tools/mr_observe_summary.py` で `mr_paper_entries_total` を確認する。
- `up_break=1` / `down_break=1` で直前OHLC足の高値/安値抜けを記録し、局面方向と一致した場合は `phase_momentum=UP_BREAK/DOWN_BREAK` になる
- 局面転換は `state._market_phase` と note の `phase_transition=A->B` 形式で保存する。通知側は `trade_notify_market_phase_enabled=1` なら転換を即時通知できる
- 日次レビューは `market_phase_outcomes` / `market_phase_transition_counts` / `observe_phase_b_n` を持ち、通知本文に `局面=... / 転換=... / B回避=N` を表示する
- shadowに `near_tp_giveback_exit_enabled=1` を追加。TPの85%以上まで近づいてから戻した玉を `exit_tech=NEAR_TP_GIVEBACK` として早逃げ検証する
- 相場流 Phase 1 を追加。`aiba_cross=KUCHIBASHI/REV_KUCHIBASHI`、`aiba_ppp=PPP/REV_PPP`、`aiba_9=1`、`aiba_try_fail=1` をnote/open_posへ保存する
- 相場流のAI反映は既定OFF。`aiba_style_ai_enabled=1` の時だけ `aiba_style_comp` として軽く加点/減点する
- `tools/trade_system_review.py` を追加。main/shadow/特徴量別成績/実効設定/未指定情報をローカルだけで総合レビューし、`review_out/` にJSON/MDを出せる。`--snapshot-dir .local_llm/vm_snapshot/latest` でVM読み取り専用snapshotも解析可能
- `tools/effective_config_dump.py` を追加。CONTROL/ai_model反映後の実効設定を朝チェック用に表示するだけで、CONTROL書込・VM再起動・外部API送信はしない
- `tools/shadow_promotion_report.py` は `feature_gate_review.status=REPORT_ONLY` として `phase` / `aiba_*` / `near_tp` / 進捗exitを可視化する。main昇格判定への自動反映はまだしない
- 日次反省はMac側通常ログが空/薄い場合に `.local_llm/vm_snapshot/latest/logs` を参照できる。反省JSONの `daily_review.report_log_source=vm_snapshot` でVM実ログ基準と確認する
- timestamp付きVM snapshotの場合、日次反省に `report_snapshot_freshness=OK/STALE/UNKNOWN` と `report_snapshot_age_min` を出して古いsnapshot誤参照を見分ける
- exit noteに `best_fav` / `max_adv` / `current_fav` を残し、日次レビュー・総合レビュー・shadow昇格レポートで `avg_mfe_pct` / `avg_mae_proxy_pct` / `avg_giveback_pct` / `progress_reached_n` を確認できる。売買判断は変えず検証用ログだけ強化
- 総合レビューは `feature_outcomes_top`（決済済み成績）と `feature_presence_top`（OBSERVE含むnote出現数）を分けて確認する
- A/B/C局面はMAで `NO_CLEAR_PHASE` になる場合、OHLCスイング/close変化から `SWING_UP` / `SWING_DOWN` / `OHLC_UP_SOFT` / `OHLC_DOWN_SOFT` / `OHLC_FLAT` へ補助判定する
- 日次通知の特徴量表は `pattern=...` / `pattern_quality=...` を拾う
- systemdテンプレートは main `300秒`、shadow `60秒`、mr_observe `60秒`。観測系だけサンプル密度を上げる

### 3-0B. 2026-04-22 追加済みロジック（セッション1）

- 安全性: `save_state()` を `.tmp → rename()` パターンに変更。ストレージ障害時の `state.json` 破損を防ぐ（POSIX `rename(2)` = atomic 保証）
- 安全性: `_cancel_orphan_orders_on_startup()` を追加。bot 起動時に取引所 ACTIVE 注文と `state._open_pos` を突合し、state 未追跡の余り注文を自動キャンセル。キャンセル履歴は `state._orphan_cancel_history` (最大50件) へ保存
- 安全性: `BitflyerPrivateClient._request()` にリトライ/バックオフを追加。HTTP 429・5xx・ネットワーク失敗時に最大3回リトライ（バックオフ 1s→2s→4s）。4xx（429除く）はリトライせず即例外。タイムスタンプ/署名は各試行で再生成
- CONTROL.csv: `rollout_mode` を CANARY → **LIVE** へ変更（CANARY 7日経過・実績確認済み）
- CONTROL.csv: `ai_auto_train_enabled` を 0 → **1** へ変更（学習ログ 131件蓄積、ゲート条件 min_samples=30 通過）
- CONTROL.csv: `ai_train_shadow_boost` を 0.70 → **0.20** へ変更（shadow PF=0.529 の低品質サンプル汚染リスクを低減）
- CONTROL.csv: `no_paper_hours` を "11,12,14,15,16" → **"14,15,16"** へ変更（11時WR=47%・12時WR=45% を開放）
- CONTROL.csv: `ai_train_weekly_bad_hours` を "" → **"14,15,16"** へ変更（WR 14時=42%/15時=38%/16時=0% に学習ペナルティ weight=0.70 を適用）
- CONTROL.csv: `daily_loss_limit_pct` を -1.0（無効）→ **-2.0** へ変更（日次損益が口座の -2% 以下になったら当日の取引停止）
- CONTROL_shadow.csv: `no_paper_hours` を "" → **"14,15,16"** へ追加（shadow の悪時間帯を MAIN に統一）
- CONTROL_shadow.csv: `ai_train_weekly_bad_hours` を "" → **"14,15,16"** へ追加（同上）
- 影響ファイル: `MAIN/bot.py`（save_state/orphan cancel）、`MAIN/exchange/bitflyer_private.py`（retry backoff）、`MAIN/CONTROL.csv`、`MAIN/CONTROL_shadow.csv`

### 3-0C. 2026-04-22 追加済みロジック（セッション2・3・4: 安全改善バッチ）

#### dashboard.py 改善
- **DEFAULTS 修正**: `product_code=FX_BTC_JPY`, `market_type=FX`, `fx_leverage=1.0`, `daily_loss_limit_pct=-2.0`, `ai_train_shadow_boost=0.20` にデフォルト値を本番実績に合わせて修正
- **S-2 マージ保存**: 設定フォーム保存時、bot の自動チューニングと競合しないようユーザー変更キーのみを新鮮なファイルへ上書き（残りはファイル最新値を維持）
- **B-1 バリデーション強化**: `_validate_control_values()` に `tp_buy_pct / tp_sell_pct / sl_pct / win_min / spread_limit_pct` の数値検証を追加
- **B-4 自動更新フラグメント**: `@st.fragment(run_every=30)` で稼働ステータス9指標を自動更新、`@st.fragment(run_every=60)` で約定テープ・セッション損益ラダーを自動更新
- **AI提案バリデーション**: `analytics:apply_weekly_ai_feedback` と `analytics:apply_loss_pattern_feedback` の CONTROL 書き込みパスに `_validate_control_values()` ガードを追加（不正な AI 提案値をブロック）
- **CONTROL変更履歴**: 設定タブに `.streamlit/dashboard_change_log.jsonl` の最新20件 CONFIG エントリを expander 形式で表示
- **P1 SIGUSR1 緊急停止**: `safety_hard_block=0→1` の CONTROL 書き込み時、`.run_lock/lockinfo.txt` の bot PID へ `SIGUSR1` を送信して sleep を即時中断。保存結果メッセージに通知結果（`bot即時通知: SIGUSR1 → pid=XXXX`）を付記
- **P3 preflight 陳腐化バナー**: LIVE モードかつ `live_preflight` が 12時間以上古い場合、全ページ上部に警告バナーを表示
- **Q1 SIGUSR1 UI フィードバック**: `write_control_kv_csv_with_log` が `safety_hard_block=1` を書いた際に SIGUSR1 結果をメッセージに含めて返す（サイレント送信から可視化へ）
- **Q4 ops_checks ステータス**: ツールタブに `live_preflight / run_check.sh / ci_check` の最終実行日時と鮮度（OK/古い・N分前）を常時表示

#### audit.py 改善
- `save_state()` を `.tmp → rename()` アトミック書き込みに変更（bot.py と同パターン統一）

#### run.py 改善
- `SIGUSR1` ハンドラを追加。`safety_hard_block=1` がダッシュボードから書き込まれると `time.sleep(300)` が即時中断され、次の bot サイクルが即座に開始される

#### VM インフラ（systemd タイマー群）
- **`ouroboros-audit.timer`**: 毎日 01:30 に `audit.py --day TODAY --fix-state` を実行（日次整合監査＋state 自動修復）。実行スクリプト: `tools/run_audit_today.sh`
- **`ouroboros-audit-weekly.timer`**: 毎月曜 02:00 に前週 Mon-Sun の週次整合監査を実行。実行スクリプト: `tools/run_audit_weekly.sh`
- **`ouroboros-state-backup.timer`**: 毎日 02:00 に `state.json / state_shadow.json / state_mr_observe.json` を `state_backups/` へバックアップ。JSON 検証済みのみコピー、30世代保持。実行スクリプト: `tools/run_state_backup.sh`

#### VM ファイル管理
- **`audit_out/` 自動クリーンアップ**: `run_audit_today.sh` が最新30件のみ保持（毎日実行時にローテーション）
- **`audit_out/` 週次クリーンアップ**: `run_audit_weekly.sh` が週次ファイルを最新20件のみ保持
- **`.bak` 自動クリーンアップ**: `write_control_kv_csv()` が CONTROL.csv バックアップを最新10件のみ保持

#### 影響ファイル（このバッチ）
- `MAIN/dashboard.py`（多数の改善）
- `MAIN/audit.py`（save_state アトミック化）
- `MAIN/run.py`（SIGUSR1 ハンドラ）
- `MAIN/tools/run_audit_today.sh`（新規 + cleanup 追加）
- `MAIN/tools/run_audit_weekly.sh`（新規）
- `MAIN/tools/run_state_backup.sh`（新規、JSON 検証付き）
- `/etc/systemd/system/ouroboros-audit.service` / `.timer`（新規）
- `/etc/systemd/system/ouroboros-audit-weekly.service` / `.timer`（新規）
- `/etc/systemd/system/ouroboros-state-backup.service` / `.timer`（新規）

### 3-0D. 2026-04-23 追加済みロジック（セッション5: システム堅牢化バッチ R1-R4）

#### R1: systemd テンプレート追加（VM 再構築安全）
- **背景**: audit / state-backup タイマーは `/etc/systemd/` に直置きされており、`install_systemd_services.sh` 再実行で消失するリスクがあった
- `deploy/systemd/` に 6 ファイルを追加:
  - `ouroboros-audit.service` / `ouroboros-audit.timer`
  - `ouroboros-audit-weekly.service` / `ouroboros-audit-weekly.timer`
  - `ouroboros-state-backup.service` / `ouroboros-state-backup.timer`
- `install_systemd_services.sh` に `--with-audit` / `--with-state-backup` フラグを追加（validation / render / cp / enable を完備）
- VM 再構築コマンド例: `./tools/install_systemd_services.sh --with-shadow --with-audit --with-state-backup --with-morning-start-check ...`

#### R2: state バックアップ破損アラート
- `run_state_backup.sh`: 破損 JSON をスキップした際に `.ops_checks.json` へ `state_backup_corrupt` エントリ（`ok: false`）を書き込む
- `run_state_backup.sh`: 正常完了時も `state_backup` エントリ（`ok: true`）を書き込む（毎日 02:00 実行後に鮮度確認可能）
- `dashboard.py` ツールタブ: `state_backup` を ops_checks パネル（max_age=26h）に追加。破損が検出された場合は `st.error` で赤アラート表示

#### R3: ダッシュボード監査レポート可視化
- `dashboard.py` ツールタブの ops_checks セクション直下に `📋 最新監査レポート` を追加
- `audit_out/audit_YYYYMMDD.json` の最新ファイルを自動読み込み
- 表示: ステータス（✅クリーン / 🟡WARN / 🟠ERROR / 🔴FATAL）、rows 数、issues 数、open pos（未クローズ）数
- issues がある場合は severity アイコン付きリストを expander 内に表示（FATAL/ERROR 時は自動展開）

#### R4: weekly audit の日付計算を Python datetime に移行
- `run_audit_weekly.sh`: `date -d "last sunday"` (Linux 専用) を Python `datetime` + `timedelta` に置換
- macOS でも動作する実装（`date -d` は macOS 非対応）
- `read -r START END < <("$VENV" - <<'PYEOF' ... PYEOF)` パターンで Python 出力を bash 変数に代入

#### 影響ファイル（このバッチ）
- `MAIN/dashboard.py`（R2 ops_checks 表示、R3 監査レポート可視化）
- `MAIN/deploy/systemd/ouroboros-audit.service` / `.timer`（R1 新規）
- `MAIN/deploy/systemd/ouroboros-audit-weekly.service` / `.timer`（R1 新規）
- `MAIN/deploy/systemd/ouroboros-state-backup.service` / `.timer`（R1 新規）
- `MAIN/tools/install_systemd_services.sh`（R1: --with-audit / --with-state-backup 追加）
- `MAIN/tools/run_state_backup.sh`（R2: 破損アラートと ops_checks 書き込み追加）
- `MAIN/tools/run_audit_weekly.sh`（R4: Python datetime に日付計算移行）

### 3-0G. 2026-04-26 追加済みロジック（セッション11: アラート強化・週次自動化）

#### 連敗停止 ntfy 通知
- **`tools/trade_event_notifier.py`** に `streak_stop` の OFF→ON 遷移検知を追加
  - `_send_event()` に `tags` / `priority` オプション引数を追加
  - cursor の初期値に `"streak_stop": None` を追加
  - 遷移検知: `streak_prev=False → streak_now=True` の場合のみ即時送信
  - Priority=high, Tags=rotating_light, ON→OFF は通知なし（朝の自動復帰に任せる）

#### 週次 TP/SL スイープ → ntfy 通知
- **`tools/weekly_auto_feedback.py`** に `_run_sweep_and_notify()` を追加
  - `run()` 末尾で非ブロッキング実行（例外はキャッチしてスキップ）
  - OHLCデータ >= 1000本 かつ バー数十分な場合のみ sweep 実行
  - 現行PFよりベストが +0.10 以上改善かつ n >= 30 サンプルの場合のみ ntfy 通知
  - CONTROL への自動書込はなし（通知のみ。手動確認後に `/backtest` で変更）

#### バックテスト学習を有効化（API上限到達後の対応）
- bitFlyer getexecutions API は 2026-03-31 より古いデータを返さない（上限到達を確認）
- 5000ページ追加fetch を試みたが API 400 で完了（これ以上の過去データ取得不可）
- **現状データ: 7,262本 (2026-03-31〜2026-04-25)、18 件のバックテストサンプル**
- WR=44.4%, PF=1.249 → ゲート条件 PF≥1.0 を通過
- ゲートを 300件 → **15件** に引き下げ、`ai_train_include_backtest=1` を有効化
  - boost=0.30x のため、18件 × 0.30 ≈ 5.4 等価サンプル（主学習 150+ 件に対して ~3.5%）
  - 主学習への影響は軽微で安全

#### 影響ファイル（このバッチ）
- `MAIN/tools/trade_event_notifier.py`（streak_stop 通知、_send_event tags/priority 追加）
- `MAIN/tools/weekly_auto_feedback.py`（週次sweep通知 _run_sweep_and_notify 追加）
- `MAIN/CONTROL.csv`（ai_train_include_backtest=1, gate=15, boost=0.30）

### 3-0H. 2026-04-26 追加済みロジック（セッション12: note CMS 中央統括）

#### 中央統括skill / agent 追加
- **`MAIN/.claude/skills/note-cms-orchestrator/SKILL.md`** を追加
  - note CMS の起動、同期、context export、役割分担の入口を中央統括側へ固定
- **`MAIN/.claude/agents/note-cms-*.md`** を追加
  - `note-cms-operator`: 起動、バックアップ、導線
  - `note-cms-editor`: 下書き、テンプレ、最終稿、X文
  - `note-cms-reviewer`: 整合性チェック、確認、公開準備
  - `note-cms-sync-manager`: Google Sheets 同期、定期実行、履歴確認

#### note CMS 担当割り当て
- `note_cms` の記事行に担当列を追加
  - `writer_agent`
  - `checker_agent`
  - `publisher_agent`
  - `x_agent`
- 役割マスタは `note_cms_data/agents.json` に分離
- Web UI に `Agents` 画面を追加し、役割定義と新規記事デフォルト担当を管理できる
- `Articles` 画面では担当ごとの完了チェックを表示
- `Agents` 画面と `Home` 画面から担当別の未完了キューを開ける
- `Home` では `自分の担当だけ固定表示` を保持できる
- `Home` の `スタートガイド` はたたみ状態を保持できる
- `Home` の `スタートガイド` から `今日の最初の1本` を作成できる
- `Home` の `スタートガイド` からテンプレを選んで `今日の1本+記事生成` を実行できる
- `Home` の `運用ヘルス` から保存URLの即時同期を実行できる
- `Home` の `運用ヘルス` から確認付きで置換同期を実行できる
- `Home` の `運用ヘルス` から `置換前CSV控え` を書き出せる
- 置換同期前に取り込みプレビューを表示する
- `Home` の担当キューから `記事生成 / 整合性チェック / X文生成` を直接実行できる
- `Home` の担当キューは `すべて / 24h超 / 72h超` で絞り込める
- `Home` の担当キューには `次に押す` の強調表示がある
- `Home` の担当キューには対象記事の最終更新からの経過時間表示がある
- `Home` の担当キューでは24時間超、72時間超の記事を段階的に強調する
- `Home` 指標に `24h超` / `72h超` の未完了キュー件数を表示する
- `Agents` 画面の `この担当をデフォルトに戻す` で役割カードの担当をそのままデフォルトへ戻せる

#### MAIN 側の実行入口
- **`MAIN/tools/run_note_cms_web.sh`**: ローカルWeb UI起動
- **`MAIN/tools/sync_note_cms_saved_google.sh`**: 保存済みGoogle Sheets URLから差分/置換同期
- **`MAIN/tools/note_cms_central_skill.py`**: `MAIN/.harness/note_cms_central_context.json` を生成
- **`MAIN/tools/note_cms_marketing_department.py`**: `MAIN/.harness/note_cms_marketing_department_context.json` を生成
- **`MAIN/tools/note_cms_healthcheck.py`**: 担当未割当、デフォルト担当不足、最新同期失敗を簡易チェック
- `summary` 1行要約も出す
- 最終同期からの経過分数も出す
- 保存URL同期が24時間を超えたら `warn`
- 保存URL同期が72時間を超えたら `error`
- **`MAIN/tools/install_note_cms_sync_launchagent.sh`** / `uninstall_note_cms_sync_launchagent.sh`
  - Mac の LaunchAgent で無料の定期同期を回せる
- 実務向け手順書は `MAIN/docs/NOTE_CMS_OPERATION_MANUAL.md`

#### 1人マーケ部門データ層
- PDF「Claude Codeで1人マーケ部門を作った全記録」の構成を note CMS 用に取り込み
- 共通判断基準は `MAIN/.claude/skills/note-cms-marketing-department/SKILL.md` に固定
- Web UI に `Write` 画面を追加。本文・URL・導線・次の操作だけに絞り、ライトテーマをデフォルト化
- 共有CSVは `note_cms_data/marketing/` に分離
  - `atoms.csv`: ニュース、体験、分析結果などのネタ原子
  - `pipeline.csv`: note / X / 図解などへの展開計画と状態
  - `outputs.csv`: 公開物URLと実績メモ
- Web UI に `Marketing` 画面を追加
  - URL / URLリスト / PDFパス / PDFフォルダ / 貼り付け本文の自動読み込み
  - 読み込み前プレビュー
  - 読み込み済みURL、PDFパス、本文ハッシュの重複スキップ
  - 読み込み実行履歴を `import_history.json` に保存
  - 読み込み履歴から `失敗だけ再実行` / `重複以外を再実行`
  - Atom追加
  - Atomからnote記事作成
  - 公開結果のoutputs登録
  - 直近7日の簡易Week Review
- 記事画面の `リンク候補プレビュー` で、完全一致リンクと関連過去記事候補を確認
- 記事画面の `自動整備` で、貼り付け本文からnote URLを抽出し、過去記事タイトルをMarkdown内部リンクに変換。関連候補は導線欄へ追加
- `MAIN/tools/note_cms_central_skill.py` の context に `marketing_department` を含める
- 詳細手順は `MAIN/docs/NOTE_CMS_MARKETING_DEPARTMENT.md`

#### 安全方針
- `note_cms/` を正本にして、`MAIN/tools` は薄い入口とcontext exportだけ持つ
- context には担当進捗と担当別の処理件数も含め、別システムはそこを読んで判断する
- note投稿は引き続き手動
- 有料API、VM deploy、systemd 変更、秘密情報の追加はなし

#### 影響ファイル（このバッチ）
- `note_cms/agent_store.py`（役割マスタ）
- `note_cms/marketing_store.py`（1人マーケ部門 共有CSV）
- `note_cms/models.py`（担当列追加）
- `note_cms/web.py`（Agents画面 / Marketing画面 / API / 記事担当欄）
- `run_note_cms.py`（agent config CLI）
- `MAIN/.claude/skills/note-cms-orchestrator/SKILL.md`
- `MAIN/.claude/agents/note-cms-operator.md`
- `MAIN/.claude/agents/note-cms-editor.md`
- `MAIN/.claude/agents/note-cms-reviewer.md`
- `MAIN/.claude/agents/note-cms-sync-manager.md`
- `MAIN/tools/run_note_cms_web.sh`
- `MAIN/tools/sync_note_cms_saved_google.sh`
- `MAIN/tools/note_cms_central_skill.py`
- `MAIN/tools/note_cms_marketing_department.py`
- `MAIN/tools/install_note_cms_sync_launchagent.sh`
- `MAIN/tools/uninstall_note_cms_sync_launchagent.sh`
- `MAIN/.claude/skills/note-cms-marketing-department/SKILL.md`
- `MAIN/docs/NOTE_CMS_MARKETING_DEPARTMENT.md`
- `MAIN/COMMANDS.md`
- `MAIN/HANDOVER.json`

### 3-0I. 2026-04-26 追加済みロジック（セッション12: daily_loss強化・KEIBA統合）

#### trade_event_notifier.py — daily_loss_alert 改善

- **Priority=high + Tags=warning 追加**: `_send_event()` 呼び出しに `tags="warning", priority="high"` を追加
  - streak_stop（Priority=high）と同レベルの緊急度として扱う
- **閾値のフォールバック**: secrets.toml に `trade_notify_daily_loss_limit_pct` が未設定の場合、
  `CONTROL.csv` の `daily_loss_limit_pct`（現在 -2.0%）を自動採用
  - 従来のデフォルト 0.5% は廃止（CONTROL.csv の実際の停止ラインに合わせる）

#### trade_event_notifier.py — streak_stop NameError バグ修正

- セッション11で追加した streak_stop 通知ブロック内の `control_values.get("streak_stop_max_losses")`
  が `main()` スコープで未定義だったバグを修正
- `_read_control_values(control_csv_path).get(...)` の即時読み取りに変更
- `py_compile` は素通りするが runtime で NameError を起こす潜在バグだった

#### KEIBA 統合（中央管理スキル追加）

- **`.claude/commands/keiba.md`** 新規作成: `/keiba` スキルとして KEIBA システム状態を確認
  - auto_cycle_status.json・prediction_feedback.csv・weekly_predictions_auto.csv を読み取り
  - 稼働状態・データ規模・予測精度（1着的中率）・launchd タイマーを表示
- **`KEIBA/.claude/CLAUDE.md`** 新規作成: KEIBA システム固有コンテキスト
  - ファイルマップ・判断ルール・連携システム定義
- **`KEIBA/.claude/commands/keiba-status.md`** 新規作成: KEIBA ディレクトリ内スキル
- **`CLAUDE.md`（ルート）更新**: 管理システム一覧にKEIBAを追加し、スキルマップを階層化
  - 新規システム追加手順（統合ガイド）を追記

#### 影響ファイル（このバッチ）
- `MAIN/tools/trade_event_notifier.py`（3点修正: NameError修正・daily_loss Priority・CONTROL fallback）
- `.claude/commands/keiba.md`（新規: /keiba スキル）
- `KEIBA/.claude/CLAUDE.md`（新規: KEIBA コンテキスト）
- `KEIBA/.claude/commands/keiba-status.md`（新規: KEIBA ローカルスキル）
- `CLAUDE.md`（KEIBA 統合、スキルマップ階層化、新規システム追加ガイド追記）

#### ダッシュボード改善・マルチプラットフォーム対応

- **`MAIN/tools/market_dashboard.html`** 新規作成: スタンドアロン Bloomberg スタイル HTML ダッシュボード
  - React なし・Python 不要。ブラウザで開くだけで動作（マルチプラットフォーム）
  - `widget_status.py` の `/widget-status.json` API（port 8787）から 30 秒ごとに自動取得
  - 表示: ボット状態バッジ・残高・日次PnL・週次PnL/WR・目標進捗・最新約定・週次棒グラフ
  - サイドバー: 鮮度・バージョン情報
  - 価格アラート: 指定価格±方向でブラウザ通知（Notification API）
  - 設定パネル: サーバー URL とトークンを localStorage に保存
  - カラーテーマ: bg=#0d1117 / surface=#161b22 / up=#3fb950 / down=#f85149 / accent=#58a6ff
  - VM デプロイ先: `/home/ubuntu/trading_bot/MAIN/tools/market_dashboard.html`

- **`MAIN/dashboard.py`（Streamlit）改善**:
  - **価格アラート機能**: Home タブに `🔔 価格アラート (BTC/JPY)` エクスパンダー追加
    - 価格水準 + 方向（以上/以下）を入力し session_state に保存
    - state.json の `_open_pos.entry_price` または `_last_ltp` と照合して発火判定
    - "set" / "clear" ボタン付き
  - **スタンドアロンダッシュボードリンク**: `🌐 スタンドアロン マーケットダッシュボード` エクスパンダー追加
    - `market_dashboard.html` のアクセス方法とトークン表示
  - バグ修正: `_load_json_obj(state_path)` → `load_json(state_path) or {}` に変更（関数名不一致）

#### 保守点検: morning_start_guard.py 構文エラー修正

- VM 版 `tools/morning_start_guard.py` の line 290 に構文エラーがあった
  - `json.dumps(...) + "\n"` の `"\n"` がファイル転送時に実際の改行文字になり、文字列がすぐ閉じられない状態になっていた
  - `py_compile` 全スクリプトスイープで検出（`python3 -m py_compile` 全 tools/*.py）
  - ローカルの正常版を VM に上書きデプロイして解消
  - このスクリプトは `ouroboros-live-preflight.timer`（09:45 JST 毎日）から呼ばれるため、修正しないと preflight が黙って失敗していた

#### 影響ファイル（ダッシュボード・保守バッチ）
- `MAIN/tools/market_dashboard.html`（新規: スタンドアロン HTML ダッシュボード）
- `MAIN/dashboard.py`（価格アラート・スタンドアロンダッシュボードリンク・_load_json_obj バグ修正）
- `MAIN/tools/morning_start_guard.py`（VM 構文エラー修正: line 290 `\n` 文字）

### 3-0L. 2026-04-26 追加済みロジック（セッション14b: 統合ダッシュボード・KEIBAステータスサーバー）

#### 統合マルチプラットフォームダッシュボード

- **`MAIN/tools/unified_dashboard.html`** 新規作成: Bloomberg ダークテーマ Vanilla JS ダッシュボード
  - CDN 依存なし・スタンドアロン（オフライン動作）
  - **SECTIONS レジストリパターン**: 新システム追加時は JS 配列に1エントリ追加するだけ
  - サイドバー: 概要 / Ouroboros FX / KEIBA 競馬 / ヘルス / [株式 SOON] / [マルチFX SOON]
  - データ源: VM `widget-status.json` + ローカル `keiba-status.json`（同時 fetch）
  - 設定パネル: WidgetURL・Bearer Token・KEIBA URL・更新間隔 → localStorage に永続化
  - 自動更新（デフォルト30秒）・手動更新ボタン
  - トップバー: Ouroboros ステータス Pill（LIVE/ブロック/エラー）+ KEIBA Pill（正常/実行中/エラー）

#### KEIBA ステータスサーバー

- **`KEIBA/keiba_status_server.py`** 新規作成: port 8789 のローカル HTTP サーバー
  - エンドポイント: `/keiba-status.json`（メイン）、`/health`
  - CORS ヘッダー付き（`Access-Control-Allow-Origin: *`）
  - 集計: auto_cycle_status.json + auto_cycle_config.json + prediction_feedback.csv + weekly_predictions_auto.csv
  - 返却フィールド: running / last_completed_at / last_success / predictions.{hit_rate_pct, recent_20_wr_pct, done, hits} / top_weekly_predictions（先頭5件）

- **`KEIBA/install_keiba_status_launchagent.sh`** 新規作成: macOS LaunchAgent インストーラー
  - ラベル: `com.ouroboros.keiba.status-server`
  - `KeepAlive: true` で常時稼働
  - ログ: `KEIBA/ci_logs/keiba_status_server.log`
  - 起動: `bash KEIBA/install_keiba_status_launchagent.sh`

#### py_compile 自動チェック Hook

- **`.claude/settings.local.json`** 更新: `hooks.PostToolUse` に py_compile フック追加
  - Edit / Write ツール実行後、`.py` ファイルへの変更を自動で構文チェック
  - `$CLAUDE_TOOL_INPUT_FILE_PATH` 変数でファイルパスを取得

#### 影響ファイル（このバッチ）
- `MAIN/tools/unified_dashboard.html`（新規）
- `KEIBA/keiba_status_server.py`（新規）
- `KEIBA/install_keiba_status_launchagent.sh`（新規）
- `.claude/settings.local.json`（py_compile hook追加）

最終更新: 2026-04-26 session14b (JST)

---

### 3-0ZJ. 2026-05-09 追加済みロジック（バックログ消化: 自動再開通知 + schemaバリデータ拡充）

#### 1. tools/morning_start_guard.py: 正常ドリフト回復パスでのカーソル書き込み追加

- **背景**: `trade_enabled_reenabled_reason` / `_at` のカーソル書き込みは `sample_recovery_mode=True` 時だけ存在し、drift→NORMAL で通常回復した場合はカーソルが書かれず `trade_event_notifier.py` の再開通知が発火しなかった。
- **変更**: lines 749-765 の `if sample_recovery_mode` ブロックの直後に `elif` を追加。
  - 条件: `not sample_recovery_mode AND trade_enabled in updates AND not dry_run AND notifier_cursor is dict`
  - reason: `drift_status==NORMAL` → `"morning_drift_normal"` / それ以外 → `f"morning_normal_recovery:drift={drift_st}"`
  - `notifier_cursor["trade_enabled_reenabled_reason"]` と `["trade_enabled_reenabled_at"]` を書き込み、カーソルファイルを保存
- これにより `trade_event_notifier.py` の既存ブロック（lines 4083-4110）が自動で拾い、ntfy に `trade_enabled_reenabled` イベントを送信する

#### 2. tools/state_schema_check.py: バリデータ拡充

- **定数追加**: `_FIB_ZONE_VALID` / `_MARKET_PHASE_VALID` / `_SHADOW_REVIEW_VALID`

- **`_check_drift_watch` 追加チェック**:
  - `normal_streak`: 存在する場合は int ≥ 0 であること（WARN）
  - `resume_ready` / `canary_ready`: 存在する場合は bool/int であること（WARN）

- **`_check_weekly_auto_feedback` 追加チェック**:
  - temporal ordering: `range_start8 > range_end8` は ERROR
  - `shadow_weekly_review.decision` が dict の場合は内部 `decision` キーを検証（WARN）; str の場合は直接検証

- **新関数 `_check_fib_last`**:
  - `zone` が `_FIB_ZONE_VALID` にない場合 WARN
  - `updated_at_jst` が空なら WARN
  - `side` が `BUY` / `SELL` 以外なら WARN

- **新関数 `_check_market_phase`**:
  - `phase` が `A` / `B` / `C` / `""` 以外なら WARN
  - `updated_at_jst` が空なら WARN

- **`check_state`**: `_fib_last` / `_market_phase` キーが存在する場合に上記チェックを呼び出すよう追加

- VM 確認: `[OK] state.json schema valid` (ローカル・VM 両方クリーン)

#### 影響ファイル
- `MAIN/tools/morning_start_guard.py`（正常再開パスへのカーソル書き込み追加）
- `MAIN/tools/state_schema_check.py`（`_fib_last` / `_market_phase` バリデーション追加・temporal ordering・`shadow_weekly_review` dict対応）

最終更新: 2026-05-09 (JST)

---

### 3-0ZK. 2026-05-10 ロジック監査 → 負け方改善（S-1 実装 + A-1 監査）

#### S-1: 早期逆行撤退 PAPER_EXIT_EARLY_ADVERSE 追加（bot.py）

- **背景**: エントリー直後から一方的に逆行する「クリーン損失」パターンに対し、既存スマート出口4種はいずれも `best_fav > 0` の回復が前提で発動しないケースがあった。
- **変更ファイル**: `bot.py`（バックアップ: `bot.py.bak.20260510-s1`）
  - **定数追加** (line ~292): `EARLY_ADVERSE_EXIT_*` 5定数
  - **RESULT_ALLOWED 追加** (line ~150): `"PAPER_EXIT_EARLY_ADVERSE"`
  - **AI_TRAIN_EXIT_RESULTS 追加**: `"PAPER_EXIT_EARLY_ADVERSE"`（AI学習対象に含める）
  - **Cfg フィールド追加** (line ~1147): `early_adverse_exit_enabled` / `only_paper` / `min_hold_min` / `loss_pct` / `max_fav_pct`
  - **CONTROL→Cfg ロード追加** (line ~1695): 上記5フィールド
  - **新関数 `resolve_early_adverse_exit_status`**: no_follow_through の直後に配置
  - **出口カスケード挿入** (TP/SL直後、no_follow_through前): `PAPER_EXIT_EARLY_ADVERSE` として独立した result を返す

- **発動条件**（すべて満たす場合）:
  - `early_adverse_exit_enabled=1`
  - hold >= 1.5分
  - current_fav <= -0.020%（逆行中）
  - best_fav <= 0.010%（ほぼ回復なし）

- **CONTROL.csv 追加キー**:
  ```
  early_adverse_exit_enabled=1
  early_adverse_exit_only_paper=0  (LIVE にも適用)
  early_adverse_exit_min_hold_min=1.5
  early_adverse_exit_loss_pct=-0.020
  early_adverse_exit_max_fav_pct=0.010
  ```

#### S-2 (既存ツール拡張): tools/smart_exit_report.py

- `EARLY_ADVERSE` を SMART_KEYS に追加
- `PAPER_EXIT_EARLY_ADVERSE` を result 直接マッチで分類（exit_tech= note依存なし）
- `hold_min` / `best_fav(MFE)` を ai_training_log から追加取得し、avg_hold・avg_MFE 列を表示

#### A-1: MR Observer OFF理由の監査

- **新ツール**: `tools/mr_observer_audit.py` → `reports/mr_observer_audit_YYYYMMDD.md|.json` 出力
- **主要発見事項**:
  1. MR Observer は `observe_only=True` 専用サブシステム（bot.py:7536 `if cfg.observe_only and cfg.mr_observe_enabled`）
  2. メインbot（observe_only=False）では CONTROL.csv で `mr_observe_enabled=1` にしても**一切発動しない**
  3. `volume_score = 1` ハードコード（bitFlyer tick に volume なし）→ max_score = 4、Rank A = 全3条件一致
  4. MR Observer をメインエントリーフィルターとして使うにはコード改修が必要
  5. `start_mr_observe.sh` による sidecar インスタンスが正規の使い方
  6. VM sidecar ログ: 過去30日で PAPER 17件、WR 65%（TP:11 SL:5）のデータあり
- **推奨**: **A: OFF維持**（メインbotには影響なし。Sidecar として継続稼働が適切）

#### VM デプロイ済みファイル
- `bot.py`（早期逆行撤退 + EARLY_ADVERSE result 型）
- `CONTROL.csv`（5キー追加）
- `tools/smart_exit_report.py`（EARLY_ADVERSE対応 + hold_min/MFE表示）
- `tools/mr_observer_audit.py`（新規）
- 構文チェック: OK / VM 動作確認: OK

最終更新: 2026-05-10 (JST)

---

### 3-0ZL. 2026-05-10 分析レポート3本追加（A-2 Shadow / A-3 AI Score / TP/SL キャリブレーション）

#### A-2: tools/shadow_quality_report.py（新規）

- Shadow ai_training_log（current + legacy）と MAIN ai_training_log を統合して比較分析
- **結論**: `ai_train_include_shadow=1` 推奨
  - Shadow WR **46.6%** > MAIN WR **44.6%**
  - Shadow 期待値 **+0.006%** > MAIN 期待値 **-0.008%**
- Shadow スコア帯別: 0.95+ → WR 65.8%, avg_ret +0.018%（最良）
- 時間帯補足: 07h(JST) WR 53.1% / 13h WR 57.6% — main bot のブロック時間が Shadow では好成績

#### A-3: tools/ai_score_quality_report.py（新規）

- live 887件（MAIN legacy 151 + Shadow legacy 700 + 最近の少数）を分析
- **スコア帯別WR**: <0.85 band は WR 41-56%、**0.95+ は WR 64%・期待値 +0.117%**（83件）
- WR 単調増加: ✗ / 期待値 単調増加: ✗ → 全体として単調性なし
- **結論**: ロット増加は現段階では根拠不足。ただし **0.95+ バンドのみ顕著に優秀** なので追跡継続
- SELL が BUY より WR/期待値ともに優位（BUY WR 44% vs SELL WR 49%）

#### 追加提案-1: tools/tp_sl_calibration_report.py（新規）

- MFE（best_fav）分布から現行 TP=0.220% の適切性を検証（887件）
- **SL 分析**: SL 353件のうち「利益圏から戻りSL（MFE≥0.05%）」が **118件(33.4%)**、即逆行SL（MFE<0.01%）**186件(52.7%)**
- **MFE 到達率**: 全トレードで TP 水準(0.22%) 到達は **25.6%** のみ
- **仮想TP シミュ**: avg_ret は現行-0.036%、0.30% TP 設定で -0.022%（最良）—しかし全水準で負
  - ⚠️ シミュ結果が全体マイナスな理由: 887件中に WR 低い旧設定期間データ多数含む（AI 閾値 0.73 引上げ前）
- **MAE 不在**: `max_adv` フィールドが ai_training_log に未記録 → SL 最適化は不可（要フィールド追加）
- **推奨**: TP は現状維持。avg_ret_TP=0.305% は TP 水準より高く、スマート出口の有効性を示す

#### VM デプロイ済みファイル
- `tools/shadow_quality_report.py`（新規）
- `tools/ai_score_quality_report.py`（新規）
- `tools/tp_sl_calibration_report.py`（新規）
- `reports/shadow_quality_report_20260510.md|.json`（VM 生成済み）

最終更新: 2026-05-10 (JST)

---

### 3-0ZM. 2026-05-10 継続実装（ai_train_include_shadow / max_adv / ログ自動探索）

#### 1. ai_train_include_shadow=1 → CONTROL.csv変更 + VM デプロイ

- **背景**: A-2 Shadow報告でShadow WR 46.6% > MAIN WR 44.6%・期待値+0.006% が確認できた
- `CONTROL.csv` の `ai_train_include_shadow` を `0` → **`1`** に変更
- VM デプロイ済み（確認: `grep ai_train_include_shadow` → `1`）
- 次回週次自動学習（`weekly_auto_feedback.py`）から Shadow トレードが含まれる（boost=0.20x）

#### 2. max_adv → ai_training_log フィールド追加（bot.py）

- **背景**: MAE（最大逆行幅）が ai_training_log に存在しないため SL 最適化分析不可（A-3報告の未解決事項）
- `bot.py` 変更（バックアップ: `bot.py.bak.20260510-maxadv`）:
  - `AI_TRAIN_FIELDS` に `"max_adv"` を追加（`best_fav` の直後）
  - `out_row.update()` に `"max_adv": op.get("max_adv", "") if same_pos else ""` を追加
  - `max_adv` はすでに `open_pos` に蓄積済み（bot.py:6912-6913）— 読み取り先は変更なし
- **スキーマ移行**: bot 起動時に `_ensure_ai_training_log_ready` がヘッダー不一致を検出し、旧 `ai_training_log.csv` を `ai_training_log.legacy_20260510122656.csv` に rename → 新スキーマでファイル再生成
- VM 確認: `head -1 ai_training_log.csv` に `max_adv` が追加済み
- 構文チェック: OK / bot 再起動: active

#### 3. tools/tp_sl_calibration_report.py — MAE 分析セクション追加

- `MAE_CHECKPOINTS` / `VIRTUAL_SL_CANDIDATES` 定数追加
- `analyse()` に MAE 分布計算・`_simulate_sl()` を追加
  - `mae_rows_valid`: `max_adv` が有効な行のみ（新スキーマ以降のトレード）
  - `vsl_sims`: MAE データが 30件以上になったら仮想SLシミュが自動的に有効化
- `format_report()` に `## MAE 分析` / `## 仮想SL シミュレーション` セクション追加
- 注意文: `"MAE フィールドは 2026-05-10 から追加、仮想SLシミュは n≥30 で自動有効化"`

#### 4. 全分析ツール → glob 自動探索に変更（ハードコードパス廃止）

- **背景**: スキーマ変更ごとに新しい `.legacy_YYYYMMDDHHMMSS.csv` が生成されるため、ハードコードパスでは新ファイルを見落とす
- 変更ファイル:
  - `tools/ai_score_quality_report.py`: `AI_LOG_SOURCES` 定数 → `_discover_ai_logs()` 関数（`ai_training_log*.csv` glob）
  - `tools/tp_sl_calibration_report.py`: 同上
  - `tools/shadow_quality_report.py`: `SHADOW_AI_LOG/MAIN_AI_LOG` 定数 → `_discover_logs(dir)` 関数 + `_load_from_list(paths)`
- VM 確認: `python3 tools/ai_score_quality_report.py --print-only` → 887件（新 legacy 含む）

#### 5. SELL 偏重エントリーの調査結果

- **887件サイド別**: BUY WR 44% / SELL WR 49%、BUY 期待値 -0.009% / SELL 期待値 +0.019%
- **時間帯×サイド分析**:
  - 10h: BUY 53% > SELL 41% — 寄り付きは BUY が優勢
  - 14h: BUY 24% < SELL 55% — 午後は BUY 壊滅（**14h は no_paper_hours でブロック済み**）
  - 15h: BUY 28% < SELL 64% — 同上（**15h もブロック済み**）
- **結論**: SELL 優位性は主に 14h・15h の午後逆張り効果に起因。現行 `no_paper_hours="12,14,15,16"` が既にこれを対処している。現行の active 時間帯（10h/11h/13h）では BUY と SELL の優劣は混在しており、サイド限定フィルターの根拠は不十分。**現状維持**。

#### VM デプロイ済みファイル
- `bot.py`（`max_adv` → AI_TRAIN_FIELDS + out_row）
- `CONTROL.csv`（`ai_train_include_shadow=1`）
- `tools/tp_sl_calibration_report.py`（MAE 分析 + glob 自動探索）
- `tools/ai_score_quality_report.py`（glob 自動探索）
- `tools/shadow_quality_report.py`（glob 自動探索）
- ai_training_log.csv スキーマ更新済み（`max_adv` フィールド追加）
- `ai_training_log.legacy_20260510122656.csv` にスキーマ移行前の 5件が保存済み

#### 次のアクション候補
- **max_adv データ蓄積待ち** → 30件以上蓄積後に `tp_sl_calibration_report.py` で仮想SLシミュを確認
- **B-1: cross_freshness 特徴量追加**（`cross_age_tick/sec/score` を AI 特徴量に追加）
- **B-2: no_paper_hours ソフトブロック**（高AIスコア時の SHADOW_SOFT_OVERRIDE 記録）
- **B-3: リジェクションログ強化**（フィルター理由付きの全拒否シグナルログ）

最終更新: 2026-05-10 セッション継続 (JST)

---

### 3-0ZN. 2026-05-10 DD評価 + PDCA運用ログ導入

#### 目的
勝率・期待値中心の評価に加え、「どれだけ沈んだか」「回復できたか」「改善施策が有効だったか」を定量管理できる仕組みを導入する。

#### 1. tools/dd_report.py（新規）

- **データ源**: ai_training_log（確定P&L `ret_pct`）をすべてのlegacyファイルも含めてglob探索
- **equity curve**: exit_time 昇順にソートし累積P&Lを構築
- **算出指標**: 全15指標
  - `daily_max_drawdown_amount` / `daily_max_drawdown_pct`（equity_peakベース; peak=0 は算出不可）
  - `daily_equity_peak` / `daily_equity_trough`
  - `dd_recovery_minutes`（最大DD後に前ピークへ回復するまでの分数）
  - `dd_recovery_count`（当期間中のDD回復回数）
  - `max_consecutive_loss` / `loss_streak_drawdown`
  - `recovery_factor` = net_pnl / abs(max_dd)
  - `profit_factor` = 総利益 / abs(総損失)
  - `expectancy_per_trade`
- **軸別分析**: 時間帯別 / AI score帯別 / exit_type別 / サイド別 / no_paper_hours状況
- **最悪取引 TOP5**: ret_pct 昇順
- **DD悪化要因**: 自動テキスト生成
- **改善候補**: PF/RF/回復状況から自動生成
- **出力**: `reports/dd_report_YYYYMMDD.md|.json`
- **注意事項**: 手数料・スプレッド未考慮 / 初期資金不明のため初期資金ベースDD率は算出不可

**VM全期間（155件 MAIN）の主要結果**:
- Net P&L: -1.383%pt（旧AI閾値期間のデータ含む）
- 最大DD: -7.715%pt、Profit Factor: 0.93、Expectancy: -0.009%pt
- no_paper_hours ブロック有: WR 36.9%（95件）vs ブロック外: WR 55.3%（60件）→ 時間帯ブロックの有効性を定量確認
- 12h は worst: net -2.685%pt（現行ブロック済み）

**バグ修正（実装中）**: `_parse_dt` の `s[:len(fmt)]` バグ（format文字列長≠日付文字列長で時刻が切れる）を `strptime(s, fmt)` に修正。

#### 2. daily_report.py — DD block 追加

- `_compute_drawdown_block(per_pos)` 関数を `main()` 内に追加
- `per_pos` の `ret_pct_est`（価格推定値）を用いて equity curve を構築
- `drawdown` キーを payload に追加（既存キーは一切変更なし）
- **注意**: daily_report の P&L は price-based 推定値。確定P&Lは `dd_report.py` を参照
- 算出指標: n_closed / max_dd / max_dd_pct / equity_peak / equity_trough / dd_recovery_minutes / dd_recovery_count / max_consecutive_loss / loss_streak / PF / RF / expectancy

#### 3. PDCA運用ログ（新規）

- `reports/pdca_log.md` — Markdown テンプレート付き運用記録
- `reports/pdca_log.json` — JSON 構造化記録（hypothesis_id / changed_control_keys / start_date / check_metrics / decision / rollback_required）
- decision は CONTINUE / ADJUST / ROLLBACK / PROMOTE / HOLD / INSUFFICIENT_DATA のいずれか
- 初期エントリー:
  - HYP-20260510-001: `ai_train_include_shadow=1`（HOLD — 週次自動学習後に確認）
  - HYP-20260510-002: `max_adv` MAE追加（HOLD — 30件蓄積後に仮想SLシミュ確認）

#### テスト結果（VM）
- T1-T10 全10件 **PASS**
  - daily_report.py 正常実行 ✓
  - 既存 daily_report JSON 破損なし ✓
  - drawdown ブロック追加確認 ✓
  - dd_report MD/JSON 生成 ✓
  - データなし日の graceful handling ✓
  - pdca_log.md/json 存在確認 ✓
  - 既存列の削除なし ✓

### 3-0ZO. 2026-05-10 DD改善機能 4件追加

#### 1. DD悪化アラート（trade_event_notifier.py）

- `dd_alert_alerted_day8` カーソルキーを追加（1日1回だけ通知）
- notifier 実行時に `reports/dd_report_YYYYMMDD.json` を読み取り
  - 当日分がなければ `reports/dd_report_all-time.json` にフォールバック
- 条件: `daily_max_drawdown_amount < -5.0` かつ `dd_recovery_minutes is None`（未回復）
- ntfy 通知: `tags=warning, priority=high`
- 例外はすべて `[WARN]` に留め、メインループは継続

#### 2. daily_ops_check.py — dd_report 自動呼び出し

- `run_daily_ops_check()` 内で `python3 tools/dd_report.py YYYYMMDD` をサブプロセス実行（timeout=30s）
- 成功時は `reports/dd_report_YYYYMMDD.json` を読み取り、5指標をレポートに含める:
  `n_trades / daily_max_drawdown_amount / profit_factor / recovery_factor / expectancy_per_trade_pct`
- `report["dd_report"]` キーに格納（既存キーは変更なし）

#### 3. PDCA自動追記（weekly_auto_feedback.py）

- 週次自動フィードバック完了後（sweep後）に `reports/pdca_log.json` を読み取り
- `decision == "HOLD"` のエントリーを探し、`reports/dd_report_all-time.json` の最新DD指標スナップショットを `result` リストへ追記
- スナップショット内容: `checked_at / n_trades / daily_max_drawdown_amount / profit_factor / recovery_factor / expectancy_per_trade_pct / dd_recovery_minutes`
- `--dry-run` 対応済み / 例外時は `[WARN]` に留め継続

#### 4. ダッシュボード DD ウィジェット（dashboard.py）

- Home タブの `_render_home_execution_section` 直後に expander `DD レポート (YYYYMMDD)` を追加
- 4カラム: 最大DD / Profit Factor / Recovery Factor / 期待値/trade
- フォールバック: `dd_report_all-time.json` を使用（当日分がない場合）
- エラー時は `st.caption()` で表示（ページクラッシュなし）

#### 5. dd_report.py — `--all-time` 出力ファイル名修正

- `--all-time` 時の出力を `dd_report_YYYYMMDD.json` → `dd_report_all-time.json` に変更
- `date_suffix = target_day if target_day else "all-time"` に修正

#### テスト結果（VM）

- `trade_event_notifier.py --dry-run` → `[OK] notifier completed sent=0` ✓（WARN なし）
- `daily_ops_check.py` → `dd_report.available: True, n_trades: 0`（当日取引なし正常）✓
- `dd_report.py --all-time` → `reports/dd_report_all-time.json` 生成確認（n=155, max_dd=-7.715）✓
- PDCA ロジック動作確認（dry-run パス、HYP-001/002 両エントリー検出）✓
- 全4ファイル `py_compile` PASS ✓

### 3-0ZQ. 2026-05-10 バンドウォーク + ローソク足パターン実装（bot v2026.05.10.1）

#### PDF資料に基づき実装した内容

**バンドウォーク (Band Walk) — ボリンジャーバンド±2σ連続カウンター**

- `update_band_walk_state(state, bb_zone, min_count)` 関数追加
- `state["_bw_buy_n"]`: bb_zone が "upper"/"break_upper" の連続評価回数
- `state["_bw_sell_n"]`: bb_zone が "lower"/"break_lower" の連続評価回数
- `bw_active`: `buy_n >= bw_walk_min_count` → "buy" / `sell_n >= min` → "sell" / otherwise "none"
- note フィールド: `ti_bw_buy_n=N ti_bw_sell_n=N ti_bw_active=buy|sell|none`
- AI特徴量: `ti_bw_active_aligned` (エントリー方向と一致) / `ti_bw_active_counter` (逆行)
- CONTROL.csv: `bw_walk_min_count=3`（デフォルト=3評価サイクル）

**BB スクイーズ (Squeeze) 検出**

- `bb_squeeze_active`: `bb_width_pct < bb_squeeze_threshold_pct` で True
- note フィールド: `ti_bb_squeeze=0|1`
- AI特徴量: `ti_bb_squeeze_active`
- CONTROL.csv: `bb_squeeze_threshold_pct=0.80`

**陽の陰はらみ / 陰の陽はらみ 検出**

- `detect_harami_pattern(bars, body_ratio_min=0.40)` 関数追加
- OHLC バーで前足=大陽線 + 当足=陰線（包含）→ `yo_no_in_harami` (BEARISH)
- 逆パターン: 大陰線 + 陽線（包含）→ `yin_no_yo_harami` (BULLISH)
- note フィールド: `harami_pat=yo_no_in_harami harami_bias=BEARISH` (パターンなし時は空)
- note に自動埋め込み → 次週の AI 学習に反映される

#### CONTROL.csv 追加パラメータ

| パラメータ | 値 | 説明 |
|-----------|-----|------|
| `bw_walk_min_count` | 3 | バンドウォーク判定に必要な連続評価回数 |
| `bb_squeeze_threshold_pct` | 0.80 | BBバンド幅(%)がこれ未満でスクイーズ判定 |

#### バージョン

bot.py: `2026.05.05.3` → `2026.05.10.1`

#### テスト結果（VM）

- `py_compile` PASS ✓
- 単体テスト: `update_band_walk_state` (buy_n=3, active=True) ✓
- 単体テスト: `detect_harami_pattern` (陽の陰はらみ検出) ✓
- VM デプロイ後 bot active ✓
- trade log で `ti_bb_squeeze=1 ti_bw_buy_n=1 ti_bw_sell_n=0 ti_bw_active=none` 記録確認 ✓
- harami: トリガー条件なし時は note に追記なし ✓

#### 設計上の選択

- Band Walk は エントリーブロックではなく **note フィールド** として記録（AI学習データ蓄積後にモデルが自動学習）
- `bw_walk_min_count=3` はデフォルト。蓄積後に /ai でモデル効果を確認してから調整可
- harami も現時点は note のみ（exit trigger は次フェーズで検討）

### 3-0ZR. 2026-05-10 Crypto Fear & Greed Index 特徴量追加（bot v2026.05.10.2）

#### 背景・目的
PDF「米国株朝刊の読み方」でCrypto F&G Indexが紹介されている。BTC専用の日次マクロセンチメント指標として、AIモデルの学習データを拡充する。

#### 実装内容

**新関数 `_fetch_crypto_fear_greed(state)`**
- API: `https://api.alternative.me/fng/?limit=1`（無料・日次更新）
- JST 09:00 頃に当日値が更新される → セッション開始（10:00 JST）時点で当日値が利用可能
- 同日は `state["_cfg_fetched_day"]` キャッシュでネットワーク呼び出しを省略
- API 失敗時は前回取得値にフォールバック（または score=-1 でスキップ）

**キャッシュフィールド（state.json）**
| フィールド | 内容 |
|-----------|------|
| `_cfg_score` | 0-100 スコア |
| `_cfg_class` | Extreme Fear / Fear / Neutral / Greed / Extreme Greed |
| `_cfg_fetched_day` | 取得日（YYYYMMDD） |

**AI 特徴量（extract_ai_features）**
| 特徴量 | 内容 |
|-------|------|
| `ti_cfg_score` | スコア整数 0-100（未取得時 None） |
| `ti_cfg_extreme_fear` | score ≤ 24 のとき True |
| `ti_cfg_extreme_greed` | score ≥ 76 のとき True |

**note フィールド**
- `cfg_score=47 cfg_class=Neutral` として feature_note に追記される

#### 設計上の選択
- **ハードフィルターではなく純粋なデータ拡充**（band walk / harami と同方針）
- AI モデルがセンチメント文脈を学習し、自動的に重みを調整することを期待
- Extreme Fear / Greed ブールで極端な相場心理を明示的に通知

#### 動作確認（2026-05-10）
```
state._cfg_score = 47
state._cfg_class = Neutral
state._cfg_fetched_day = 20260510
```
API 取得成功確認 ✓（bot v2026.05.10.2 でデプロイ済み）

#### 適用しなかったPDFコンセプト（精査結果）
| PDF | 内容 | 不適用理由 |
|-----|------|-----------|
| 高配当株の選び方 | PER/PBR/ROE/配当性向 | 長期株式ファンダメンタル；BTC FX日中と無縁 |
| デイトレ禁止銘柄 | 出来高/低位株/信用倍率/決算前 | 株固有メカニズム（信用倍率・希薄化）はBTC FXに存在しない |
| 「寄り付き後15分待つ」 | 株市場開始直後の高ボラ回避 | BTC は24/7連続市場；「寄り付き」メカニズムなし |
| テック株急落の今こそ狙い目 | 個別株推奨12銘柄 | 株アナリスト情報；BTC FX に無関係 |

### 3-0ZP. 2026-05-10 PDCA日次自律評価システム

#### 目的
PDCAを週次から**日次**に拡張し、ルールベースの自動判断ヒントを生成する完全自立型の評価サイクルを構築する。

#### tools/pdca_daily_update.py（新規）

- **実行タイミング**: 毎日 21:00 JST（systemd） + daily_ops_check から呼び出し + weekly_auto_feedback から委譲
- **処理フロー**:
  1. `dd_report.py YYYYMMDD` + `dd_report.py --all-time` をサブプロセス実行
  2. `reports/pdca_log.json` の HOLD エントリーに日次スナップショットを追記
  3. ルールベース自動判断ヒントを計算
  4. `reports/pdca_daily_YYYYMMDD.json` に保存
  5. ntfy 通知（緊急ヒント時は priority=high）

- **自動判断ヒント（auto_decision_hint）の判定ルール**:
  | ヒント | 条件 |
  |--------|------|
  | `INSUFFICIENT_DATA` | N < 10件 |
  | `ROLLBACK_CANDIDATE` | PF < 0.85 または 最大DD が最初スナップ比 -1.0%pt 悪化 |
  | `CONTINUE_CANDIDATE` | 直近3スナップすべて PF ≥ 1.05 |
  | `REVIEW_DUE` | 開始から14日以上経過 |
  | `HOLD` | 上記いずれにも該当しない |

- `--dry-run` / `--no-notify` / `--day8` オプション対応

#### daily_ops_check.py 変更点

- `run_daily_ops_check()` 内で `pdca_daily_update.py --no-notify` をサブプロセス実行
- `report["pdca_daily"]` キーに `{available, hints, updated_entries, error}` を追記

#### weekly_auto_feedback.py 変更点

- 旧インライン PDCA 追記を削除 → `pdca_daily_update.py` へ委譲（`--no-notify` で重複通知回避）

#### systemd timer

- `deploy/systemd/ouroboros-pdca-daily.service|.timer`
- 毎日 **21:00 JST** に実行（市場クローズ 17:00 JST + 4時間余裕）
- VM インストール済み・enabled・次回発火: 2026-05-10 21:00 JST

#### PDCA実行フロー（全体像）

```
09:00 JST  signal-outcome-daily（シグナル確認）
17:00 JST  市場クローズ
21:00 JST  ★ pdca-daily.timer → pdca_daily_update.py
           └─ dd_report（当日 + 全期間）生成
           └─ pdca_log.json 更新（スナップショット追記 + ヒント計算）
           └─ ntfy PDCA日次レポート送信
随時        daily_ops_check (5分毎) も pdca_daily_update --no-notify を実行
毎月曜      weekly_auto_feedback → pdca_daily_update --no-notify に委譲
```

#### テスト結果（VM）

- `pdca_daily_update.py --dry-run` → PDCA ヒント計算・ファイル保存 dry-run 正常 ✓
- `pdca_daily_update.py --no-notify` → `pdca_daily_20260510.json` 生成、`pdca_log.json` 更新 ✓
  - HYP-001/002 両エントリー: hint=HOLD / snapshots=1 / pf=0.931 ✓
- systemd timer `active (waiting)` 次回 21:00 JST ✓
- `py_compile` 全3ファイル PASS ✓

#### VM デプロイ済みファイル
- `daily_report.py`（DD block 追加。バックアップ: `daily_report.py.bak.20260510-dd`）
- `tools/dd_report.py`（新規）
- `reports/pdca_log.md`（新規）
- `reports/pdca_log.json`（新規）
- `reports/dd_report_20260510.md|.json`（VM 生成済み）

#### 追加提案（次に検討すべき改善）
1. **PDCAの自動評価**: `weekly_auto_feedback.py` の週次実行後に DD指標を自動でPDCAログに追記するツール
2. **daily_report への dd_report 統合**: daily_ops_check.py または daily_report.py から `dd_report.py` を自動呼び出し、`reports/dd_report_YYYYMMDD.md` を当日生成する
3. **DD悪化アラート**: dd_recovery_count=0 かつ max_dd < -5%pt の場合に ntfy 通知
4. **ダッシュボード DD ウィジェット**: widget_status.py または dashboard.py に daily_max_drawdown / PF を1行表示

最終更新: 2026-05-10 (JST)

---

### 3-0M. 2026-04-29 追加済みロジック（セッション23: 保守点検・AIゲート修正・ダッシュボード強化）

#### 保守点検結果
- 全サービス正常稼働（system-level systemd: bot/shadow/mr-observe/widget/dashboard/ngrok）
- ディスク使用率: 37%（45GB中17GB使用）、ログ: 168ファイル×168MB
- timer一覧: ntfy-price-alert(5分), monthly-ai-report(5/1), weekly-autotrain(月曜00:20) 正常
- PF=1.538、AI gate pass_rate=40.6%（14日）

#### G2: ai_score_bad_hours 修正（AIゲート13時ペナルティ削除）
- **背景**: ai_training_logで13時WR=60%+にもかかわらず -0.10 ペナルティが付与されており、設定と実績が乖離
- **変更**: `ai_score_bad_hours`: `13` → `""` (空欄、ペナルティなし)
- **VM + Local CONTROL.csv 両方更新**, SIGHUP で即反映
- **注意**: 10h AIブロック率72%は意図的な可能性あり（モデルが10h特有パターンを学習中）。現時点は監視継続。

#### G1: 週次ntfyレポートにPF/avg_ret追加
- **`tools/send_weekly_summary_ntfy.py`**: `_build_ai_perf_line()` 関数追加
  - ai_training_log.csv の直近4週データから WR・PF・avg_ret を計算
  - 送信例: `✅ AI学習ログ4週: WR=53% PF=1.54 avg=+4.325% N=32`
- VM デプロイ済み、テスト送信 HTTP 200 確認

#### G3: ダッシュボード「最新約定」UI強化
- **`tools/unified_dashboard.html`**: `renderLatestTrade()` を強化
  - エントリー価格 + エグジット価格を両方表示
  - 決済理由を色分け: TP→緑(✅) / SL→赤(🛑) / スマート出口→黄(🧠)
  - スマート出口の細分化: NearTP / 弱進行 / 反転 / 不追従 を日本語ラベル表示
- VM デプロイ済み

#### ＃AI搭載: ローカルLLM (Ollama) 既存状況
- Ollama は既に VM に導入済み。モデル: qwen2.5:0.5b (397MB) / 1.5b (986MB) / 3b-instruct (1.9GB)
- `weekly_auto_feedback.py` が `--llm-mode auto --ollama-model qwen2.5:0.5b` で週次AI分析を実施
- `trade_event_notifier.py` の日次反省も Ollama (qwen2.5:1.5b) でフォールバック実装済み
- さらなる自律化は「signal品質のLLM評価」「LLMによるCONTROL.csv自動推奨」が次のステップ

#### 影響ファイル（このバッチ）
- `MAIN/CONTROL.csv`（ai_score_bad_hours: "13" → ""）
- `MAIN/tools/send_weekly_summary_ntfy.py`（PF/avg_ret行追加）
- `MAIN/tools/unified_dashboard.html`（最新約定UI強化）

最終更新: 2026-04-29 session23 (JST)

### 3-0N. 2026-04-29 追加済みロジック（セッション24: 6項目改善バッチ）

#### 1. Ollama 3b-instruct 移行（週次AI分析品質向上）
- `/etc/systemd/system/ouroboros-weekly-autotrain.service`: `--ollama-model qwen2.5:0.5b` → `qwen2.5:3b-instruct`
- `daemon-reload` 済み。次回月曜00:20の週次自動学習から3bモデルで分析

#### 2. AIゲートブロックスコア可視化
- **`tools/widget_status.py`**:
  - `_parse_ai_block_score()` 関数追加: note フィールドから `score=X.XXX` を正規表現抽出
  - `_build_ai_gate_snapshot()` 強化: `block_avg_score`, `block_min_score` をby_hour別・全体で集計
  - `ai_gate` JSON に `ai_threshold` (CONTROL.csv の ai_threshold 値) を追加
- **`tools/unified_dashboard.html`**: AIゲート時間帯テーブルに「ブロック平均score」列追加
  - 閾値との差が 0.05 未満の場合 `warn` 色で強調
  - テーブル下に全体統計 `avg_score / min_score / 閾値` を表示

#### 3. スマート出口効果測定スクリプト
- **`tools/smart_exit_report.py`** 新規作成（VM にデプロイ済み）
  - 実行: `python3 tools/smart_exit_report.py [--days N] [--ntfy]`
  - trade_log の exit_tech= + ai_training_log の ret_pct を pos_id で JOIN
  - NTP/PR/WP/NF 別の件数・avg_ret・WR を集計
  - **現状**: 過去60日でスマート出口発動 0件（条件がまだ厳しすぎる可能性）

#### 4. Shadow A/B — is_shadow をai_training_logに追加
- **`bot.py`**: `AI_TRAIN_FIELDS` に `is_shadow` 追加、書き込み時に `INSTANCE_NAME != "main"` で設定
- **VM ai_training_log.csv**: 既存143行を is_shadow=0 で保持したままカラム追加（backup あり）
- **bot.py SIGHUP** 送信済み（PID 142887）
- これで Shadow/MAINの学習分離トラッキングが開始

#### 5. CONTROL.csv git自動コミット
- **`tools/control_git_sync.sh`** 新規作成（VM に配置）
  - CONTROL.csv / CONTROL_shadow.csv の git diff を検知し自動コミット
  - 変更キー一覧をコミットメッセージに記録
- **`/etc/systemd/system/ouroboros-control-git.path`**: CONTROL.csv 変更を inotify で検知
- **`/etc/systemd/system/ouroboros-control-git.service`**: oneshot で git commit 実行
- `systemctl enable --now ouroboros-control-git.path` 有効化済み

#### 6. Dashboard バグ修正
- `renderPortfolio()` に `const daily = ob?.goal?.pnl_jpy ?? null;` 追加（`Can't find variable: daily` エラー修正）
- ウォッチリスト未取得時に「⏳ 価格取得中...」を表示

#### 影響ファイル（このバッチ）
- `/etc/systemd/system/ouroboros-weekly-autotrain.service`（VM: Ollamaモデル変更）
- `MAIN/tools/widget_status.py`（AIブロックスコア集計追加）
- `MAIN/tools/unified_dashboard.html`（AIゲートテーブル強化 + portfolioバグ修正）
- `MAIN/tools/smart_exit_report.py`（新規）
- `MAIN/tools/control_git_sync.sh`（新規、VMのみ）
- `/etc/systemd/system/ouroboros-control-git.{path,service}`（新規）
- `MAIN/bot.py`（AI_TRAIN_FIELDS に is_shadow 追加）

#### スマート出口 未発動の背景
60日間でスマート出口0件の理由：
- NO_FOLLOW_THROUGH: `max_current_fav_pct=0.00` が極端に厳しい（現在含み益>0なら発動しない）
- NEAR_TP_GIVEBACK: TP=0.220% × 75% = 0.165% 到達後に0.04%戻す条件は高TP率のため通過
- WEAK_PROGRESS: min_hold=30分は多くの取引がTP/SLで解消される前の時間

最終更新: 2026-04-29 session24 (JST)

### 3-0P. 2026-04-29 追加済みロジック（セッション26: 追加改善バッチ）

#### CONTROL.csv 変更（VM + Local, SIGHUP PID 147949）

| フィールド | 変更前 | 変更後 | 理由 |
|---|---|---|---|
| `ai_time_good_hour_boost` | 0.10 | **0.13** | 10h block_avg_score=0.605 + 0.13 = 0.735 > 閾値0.73。AIブロック解消 |
| `weak_progress_exit_min_hold_min` | 30 | **20** | スマート出口 WEAK_PROGRESS の発動頻度向上 |

#### shadow_ab_compare.py: `--ai-log` モード追加
- `tools/shadow_ab_compare.py` に `--ai-log` フラグを追加
- `logs/ai_training_log.csv`（MAIN）と `logs/instances/shadow/ai_training_log.csv`（Shadow）を読んで WR/PF/avg_ret を並列比較
- 時間帯別内訳表示付き。2026-05-13 以降に `python3 tools/shadow_ab_compare.py --ai-log --since 20260425` で評価可能
- 既存のデフォルトモード（trade_log ファイルで buy_fast_ma A/B 比較）は引き続き動作

#### send_weekly_summary_ntfy.py: BOT_VERSION 追加
- `_read_bot_version()` 関数追加（bot.py 先頭20行から `BOT_VERSION=` を読む）
- 週次レポート1行目: `✅ Ouroboros 週次レポート v1.25.0 2026/04/21〜27` 形式に変更

#### weekly_auto_feedback.py: 時間帯別WR → LLM プロンプト
- `_build_ai_log_hour_stats(ai_log_path, lookback_days=28)` 関数追加
- `ai_training_log.csv` から時間帯別 WR/N を計算して文字列化
- `_build_weekly_llm_prompt()` に `ai_log_hour_text` 引数を追加し、プロンプト末尾に付与
- LLM（3b-instruct）が時間帯情報を根拠に good/bad hours の提案精度が向上
- 書式例:
  ```
  ai_training_hourly_wr (過去28日):
    10h WR=57% N=14
    11h WR=45% N=11
    13h WR=67% N=6
  ```

#### 影響ファイル（このバッチ）
- `MAIN/CONTROL.csv`（ai_time_good_hour_boost: 0.10→0.13, weak_progress_exit_min_hold_min: 30→20）
- `MAIN/tools/shadow_ab_compare.py`（--ai-log モード追加）
- `MAIN/tools/send_weekly_summary_ntfy.py`（BOT_VERSION ヘッダー追加）
- `MAIN/tools/weekly_auto_feedback.py`（_build_ai_log_hour_stats + LLM prompt 拡張）

最終更新: 2026-04-29 session26 (JST)

---

### 3-0Q. 2026-04-29 追加済みロジック（セッション27: AIゲート修正・スマート出口緩和）

#### バグ修正: ai_model.json と CONTROL.csv の ai_threshold 不整合

- **背景**: CONTROL.csv `ai_threshold=0.73` はセッション内で変更されていたが、ボットが実際に使うゲート閾値は `ai_model.json["confidence_threshold"]["entry"]` から読む。VM の `ai_model.json` は `0.70` のままだったため、意図した `0.73` ゲートが機能していなかった。
- **変更**: `ai_model.json["confidence_threshold"]["entry"]`: `0.70` → `0.73`（VM + Local 両方）
- SIGHUP 送信済み（PID 149533）
- これにより、意図通り 0.73 ゲートが有効化される。10h の avg_score+boost ≈ 0.735 > 0.73 で引き続き通過可能。

#### スマート出口条件緩和: no_follow_through_exit_max_best_fav_pct

- **背景**: 30日間スマート出口0件。`no_follow_through_exit_max_best_fav_pct=0.01%` が極端に厳しく（0.01%でも有利方向に動いた場合は発動しない）、ほぼ「一切動かなかった取引」しか対象にならなかった。
- **変更**: `no_follow_through_exit_max_best_fav_pct`: `0.01` → `0.03`（VM + Local, SIGHUP済み）
- 0.03%以内の微小有利動作後に平場/逆行している場合は早期撤退する

#### 影響ファイル（このバッチ）
- `MAIN/CONTROL.csv`（no_follow_through_exit_max_best_fav_pct: 0.01→0.03）
- `MAIN/ai_model.json`（confidence_threshold.entry: 0.70→0.73）

最終更新: 2026-04-29 session27 (JST)

---

### 3-0R. 2026-04-29 追加済みロジック（セッション29: バージョン管理統一）

#### BOT_VERSION 削除 → OUROBOROS_BOT_VERSION に一本化

- **背景**: `BOT_VERSION = "1.25.0"`（セマンティック形式、bot.py 先頭）と `OUROBOROS_BOT_VERSION = "2026.04.29.1"`（日付形式、bot.py 本体）の 2 変数が並走しており、どちらが正かわからない状態だった。
- **変更**: `BOT_VERSION` を bot.py から削除。`OUROBOROS_BOT_VERSION` を唯一の真のバージョン変数とする（`2026.04.29.1` → `2026.04.29.2`）。
- **send_weekly_summary_ntfy.py**: `_read_bot_version()` を `OUROBOROS_BOT_VERSION` スキャン（先頭60行）に更新。週次レポートヘッダーが `2026.04.29.2` 形式で表示される。
- SIGHUP 送信済み（PID 152457）

#### 影響ファイル
- `MAIN/bot.py`（BOT_VERSION 削除、OUROBOROS_BOT_VERSION: 2026.04.29.1 → 2026.04.29.2）
- `MAIN/tools/send_weekly_summary_ntfy.py`（_read_bot_version: BOT_VERSION → OUROBOROS_BOT_VERSION）

最終更新: 2026-04-29 session29 (JST)

---

### 3-0S. 2026-04-29 追加済みロジック（セッション30: 自動再開通知・Widget日次PnL）

#### 1. trade_event_notifier.py: 取引自動再開通知

- **背景**: `morning_start_guard` が drift 回復後に `trade_enabled=1` を自動復帰する際、既存のカーソルに `trade_enabled_reenabled_reason` / `_at` を書き込んでいたが、`trade_event_notifier.py` がこれを読んで ntfy 通知を送る処理が存在しなかった。
- **変更**: カーソルデフォルトに `trade_enabled_reenabled_notified_at` を追加。drift ウォッチブロックの直後に再開通知ブロックを追加。
- 検知条件: `reenabled_reason` 非空 かつ `reenabled_at != reenabled_notified_at`（重複送信防止）
- 通知内容: イベント名 `trade_enabled_reenabled` / 再開理由 / 再開時刻 / ホスト
- クールダウン: `state_change_min_interval_sec` 共用

#### 2. widget_status.py: 当日 PnL フィールド追加

- **背景**: `goal.pnl_jpy` はネストされているため iOS ウィジェットが直接参照しにくく、また logs_dir=None 時の 0.0 が「未取得」と区別できなかった。
- **変更**:
  - `_build_daily_goal_snapshot()` に `pnl_available: bool` フィールドを追加。logs_dir が None の場合 `pnl_jpy=None`, `closed_n=None` を返す（0.0 との区別）
  - `build_widget_status()` の return に `daily_pnl_jpy` / `daily_closed_n` / `daily_pnl_available` をトップレベルに追加（フラット参照）
- `ouroboros-widget-status.service` 再起動済み

#### 影響ファイル
- `MAIN/tools/trade_event_notifier.py`（trade_enabled_reenabled 通知追加）
- `MAIN/tools/widget_status.py`（daily_pnl_jpy / pnl_available 追加）

### 3-0T. 2026-04-30 追加済みロジック（セッション31: state スキーマバリデータ・Shadow SL 分類）

#### 1. tools/state_schema_check.py（新規）

- **背景**: `_drift_watch` / `_weekly_auto_feedback` のキー欠損・型不整合・矛盾状態（frozen_by_drift=True だが train_freeze_applied=False など）を人手で気づく前に検出できていなかった。
- **変更**: 新規ツール `tools/state_schema_check.py` を追加。`_drift_watch` および `_weekly_auto_feedback` のスキーマを検証し、ERROR / WARN を報告。
- 主なチェック項目:
  - `status` が既知セット内か
  - `recent_metrics` / `baseline_metrics` の `closed_n` が非負か
  - `frozen_by_drift=True` かつ `train_freeze_applied=False` の矛盾
  - `trade_paused_by_drift=True` かつ `trade_pause_applied=False` の矛盾
  - `weekly_report_recent_rc` / `weekly_report_baseline_rc` が非ゼロ（週次レポート失敗）
  - `_weekly_auto_feedback.range_start8` / `range_end8` が 8 桁日付か
- 実行: `python3 tools/state_schema_check.py [--state-path PATH] [--print-json]`
- VM での確認: `[OK] state.json schema valid`

#### 2. tools/shadow_promotion_report.py: Shadow SL 分類追加

- **背景**: SL 件数だけでは「エントリー方向が初めから間違っていた（reversal_wrap）」と「TP 手前まで行って戻された（profit_miss）」が区別できず、shadow 昇格判断の分析精度が低かった。
- **変更**: `_classify_shadow_sl()` を追加。`PAPER_EXIT_SL` 行の `best_fav` を参照して 3 分類。
  - `reversal_wrap` : best_fav < 0.033% （TP の 15% 未満 — エントリー直後に逆行）
  - `profit_miss`   : best_fav ≥ 0.077% （TP の 35% 以上 — 利益域まで進んでから SL）
  - `middle`        : その間
- `build_report()` の shadow dict に `sl_classification` キーを追加
- `format_text()` の末尾に `sl_classification=...` の 1 行を追加
- 既存の昇格判断ロジック（`_decide()`）への影響なし（REPORT_ONLY）

#### 影響ファイル
- `MAIN/tools/state_schema_check.py`（新規）
- `MAIN/tools/shadow_promotion_report.py`（sl_classification 追加）

### 3-0U. 2026-05-01 追加済みロジック（セッション32: /status schema 組み込み・weekly LLM SL 分類）

#### 1. /status コマンドに state_schema_check 組み込み

- **背景**: 毎朝 /status を実行するだけで state.json スキーマ異常を即時検出できるよう、schema check を自動組み込みにした。
- **変更**: `.claude/commands/status.md` の SSH Python ブロックに追加。
  - `tools/state_schema_check.py` の `check_state()` を直接 import して実行。
  - ops_checks セクションに `🟢/🔴 state_schema: <結果>` を1行追加。
  - issues リストに `state.json schema ERROR` を追加（総合判定に反映）。
  - import 失敗時は ok=True として status 自体のクラッシュを防ぐ。

#### 2. weekly_auto_feedback.py: Shadow SL 分類を LLM プロンプトに追加

- **背景**: reversal_wrap 率が高い週（エントリー方向ミス多発）を LLM が認識できず、提案精度が低かった。
- **変更**: `tools/weekly_auto_feedback.py` に以下を追加。
  - `_get_days_between(start8, end8)`: 週次レポートの日付範囲を YYYYMMDD リストに変換するヘルパー。
  - shadow_logs_dir + range_start8/end8 が揃っている場合、`shadow_promotion_report._classify_shadow_sl()` を呼び出して `shadow_sl_cls` を取得。
  - `_build_weekly_llm_prompt()` に `shadow_sl_cls` パラメータを追加。
  - 判断ヒント: `reversal_wrap_pct > 50% → エントリー精度低下を明示` を追加。
  - プロンプトデータ行: `shadow_sl_classification: total=N reversal_wrap=N(XX%) profit_miss=N(XX%) middle=N` を追加。
  - sl_n=0（SL なし）の週はデータ行をスキップ（プロンプト長を無駄に増やさない）。

#### 影響ファイル
- `.claude/commands/status.md`（state_schema 表示・issues 追加）
- `MAIN/tools/weekly_auto_feedback.py`（_get_days_between 追加・shadow_sl_cls LLM 組み込み）

最終更新: 2026-05-01 session32 (JST)

### 3-0V. 2026-05-02 追加済みロジック（セッション33: MR PAPER exit レポート・weekly schema guard・ntfy SL 分類）

#### 1. tools/mr_observe_summary.py: MR PAPER exit TP/SL/TIMEOUT 内訳追加

- **背景**: `mr_paper_entries_total` だけでは PAPER 玉の結果（TP/SL/TIMEOUT）が分からず昇格判断に不足。
- **変更**: `_mr_paper_exit_breakdown()` 関数を追加。
  - MR PAPER エントリー行の `pos_id` を収集し、`PAPER_EXIT_*` 行を突合してカウント。
  - 分類: `tp_n` (PAPER_EXIT_TP) / `sl_n` (PAPER_EXIT_SL) / `timeout_n` (TIMEOUT/EOD/PRENEWS) / `other_n`
  - `wr_pct` = tp_n / total_n × 100
- `build_summary()` / `build_multi_day_summary()` に `mr_paper_exit_breakdown` フィールドを追加。
- `format_text()` / `format_multi_text()` に `mr_paper_exit_breakdown=` / `mr_paper_exits=` を追加。
- **実績**: `--multi-day --lookback-days 7` で確認 → `tp_n=3 wr_pct=100.0` (04-30: 3件全TP)

#### 2. ouroboros-weekly-autotrain.service: ExecStartPre schema check

- **変更**: `ExecStartPre=.../python tools/state_schema_check.py` を追加。
- schema ERROR（frozen_by_drift 矛盾など）の場合、ExecStart（週次自動学習）はスキップされる。
- WARN のみ（exit 0）は正常通り実行。
- 影響: `deploy/systemd/ouroboros-weekly-autotrain.service` + VM `/etc/systemd/system/` 直接更新。
- `systemctl daemon-reload` 済み。

#### 3. tools/weekly_auto_feedback.py: shadow_sl_cls を state.json に保存

- `_weekly_auto_feedback` 辞書に `"shadow_sl_cls": shadow_sl_cls` を追加。
- send_weekly_summary_ntfy.py が読み取れるよう state 経由でデータを渡す。

#### 4. tools/send_weekly_summary_ntfy.py: Shadow SL 分類を ntfy 通知に追加

- `waf.get("shadow_sl_cls")` から reversal_wrap_pct を読み取り、SL がある週は通知に追加。
- `reversal_wrap_pct > 50%` の場合は ⚠️ アイコン付きで表示。

#### 影響ファイル
- `MAIN/tools/mr_observe_summary.py`（MR PAPER exit 内訳追加）
- `MAIN/tools/weekly_auto_feedback.py`（shadow_sl_cls 保存）
- `MAIN/tools/send_weekly_summary_ntfy.py`（SL 分類 ntfy 追加）
- `MAIN/deploy/systemd/ouroboros-weekly-autotrain.service`（ExecStartPre 追加）

最終更新: 2026-05-02 session33 (JST)

---

### 3-0ZD. 2026-05-04 追加済みロジック（セッション43: シャドウ bot 強化 E〜H）

#### E. ML モデル初版 (`stock_ml_train.py`)

- numpy のみで実装したロジスティック回帰（scikit-learn 不要）
- バックテスト CSV を読み込み BUY→SELL ペアを組み、エントリー時の特徴量でラベルを予測
- 特徴量: `sma_ratio = sma5/sma20`, `rsi_norm = rsi14/100`
- モデル保存先: `review_out/stock_ml_model.json`（weights + bias + metadata）
- `stock_shadow_bot.py --ml-filter --ml-min-prob 0.55` で BUY シグナルをゲート
- 初回 30 日バックテスト 110 サンプルで学習済み（WR=48.2%、精度 51.8% — サンプル増加で改善予定）

```bash
python3 stock_shadow_bot.py --backtest --backtest-days 30   # データ収集
python3 stock_ml_train.py --eval                            # 学習＋評価
python3 stock_ml_train.py --predict 1.025 58.0              # 単発予測
python3 stock_shadow_bot.py --ml-filter                     # ML ゲート有効
```

#### F. シグナル重複排除（SELL 後 2h クールダウン）

- SELL 後 `REENTRY_COOLDOWN_HOURS=2` 間は同銘柄の再エントリーをブロック
- `state.cooldown_until[symbol]` に期限時刻を保存
- ブロック時は `COOLDOWN` 理由で HOLD として CSV に記録
- ホイップソー（即座の往復売買）を防止

#### G. ダッシュボード シグナルウォッチリスト

- run ごとに全銘柄の最新シグナルを `state.last_signals` に保存
  - `price, sma5, sma20, rsi14, action, reason, ts` を格納
- `_renderShadowPanel()` にウォッチリストテーブルを追加
  - SMA比（>1=緑）、RSI（>70=赤/<35=緑）、シグナル色分け
  - クールダウン中の銘柄に ⏳ アイコン

#### H. 週次サマリー通知 (`stock_shadow_weekly.py`)

- 直近 7 日の CSV を集計: トレード数・勝率・銘柄別 PnL を整形
- ntfy / webhook（secrets.toml 設定済みの場合）に自動送信
- 未設定時は `review_out/stock_shadow_weekly.txt` に保存
- systemd timer: 毎週日曜 JST 08:00（`ouroboros-stock-shadow-weekly.timer`）

```bash
python3 stock_shadow_weekly.py --dry-run       # 内容確認のみ
python3 stock_shadow_weekly.py                 # 実際に送信
```

#### ファイル（セッション43追加）
- `MAIN/stock_ml_train.py`（新規）
- `MAIN/stock_shadow_weekly.py`（新規）
- `MAIN/stock_shadow_bot.py`（F/G 追加更新）
- `MAIN/tools/unified_dashboard.html`（G: ウォッチリスト追加）
- `MAIN/deploy/systemd/ouroboros-stock-shadow-weekly.service`（新規・VM 有効化済み）
- `MAIN/deploy/systemd/ouroboros-stock-shadow-weekly.timer`（新規・VM 有効化済み）

#### 動作確認
- backtest 30日: 6銘柄 110トレード、WR=48.2%, PnL=$+31.59
- ML学習: 51.8% 精度（重み微小 → サンプル蓄積後に再学習推奨）
- weekly dry-run: NVDA $-0.03 / 直近7日サマリー正常生成
- timers: `ouroboros-stock-shadow.timer` 次回 JST 22:00, `ouroboros-stock-shadow-weekly.timer` 次回 5/10 JST 08:00

---

### 3-0ZE. 2026-05-04 追加済みロジック（セッション44-45: シャドウbot強化 J/K2/L/N/O/P/Q/R/S + シグナルスキャナー）

#### J. ML 5特徴量拡張（`stock_ml_train.py` + `stock_shadow_bot.py`）

- `FEATURE_NAMES = ["sma_ratio", "rsi_norm", "vol_ratio", "price_dev", "prev_return"]`
- `vol_ratio = 直近vol / 20期間平均vol`（出来高比）
- `price_dev = (price - sma20) / sma20`（乖離率）
- `prev_return = (close[-1] - close[-2]) / close[-2]`（前期リターン）
- `extract_samples()` が旧CSVに欠落カラムがある場合はデフォルト値（1.0/0.0/0.0）で補完
- `_ml_predict()` がモデルの特徴量長と不一致の場合は旧2特徴量フォールバック

#### K2. リアルタイム BUY/SELL ntfy 通知

- `_send_trade_notify(action, symbol, price, pnl, interval, extra="")` 追加
- BUY 時: Priority=default, SELL 時: PnL 結果付き（利益=Priority low / 損失=high）
- ntfy_topic_url が secrets.toml に未設定の場合はサイレントスキップ

#### L. マルチタイムフレームフィルター（`--mtf-filter`）

- `_check_daily_trend(symbol)` → 日足 SMA5 > SMA20 の場合 True
- `mtf_filter=True` 時: BUY エントリーには「日足が強気」を必須条件とする
- `--mtf-filter` CLI フラグで有効化。daily_bull 結果は last_signals に保存

#### Q. ストップロス（`--stop-pct` デフォルト -2%）

- エントリー価格から `stop_pct` 以上の下落で SELL/STOP_LOSS を発動
- HOLD チェックより前に評価（ポジション保有中かつ stop_pct<0 の場合）
- `--stop-pct -0.02`（-2%）がデフォルト

#### R. 監視銘柄 9 種追加

- `DEFAULT_SYMBOLS = ["AAPL","MSFT","NVDA","TSLA","QQQ","SPY","AMZN","META","AMD"]`
- systemd service に `--symbols AAPL,MSFT,NVDA,TSLA,QQQ,SPY,AMZN,META,AMD` 反映

#### 追加安全機能（Q バッチ同梱）

- `max_positions=3`: ポジション上限超過で BUY をブロック
- `daily_loss_limit=-50.0 USD`: 当日損失がこの値以下になったら当日の BUY を停止
- `commission=1.0 USD/注文`: SELL 時に2×手数料を PnL から差し引く
- Drawdown トラッキング: `peak_pnl`, `max_drawdown_usd` を state.json に保存

#### S. 週次勝率履歴 + 実弾準備スコア（`stock_shadow_weekly.py` 完全書き換え）

- `compute_winrate_history(weeks=4)` → 過去4週の {trades, wins, pnl, win_rate} リスト
- `check_live_readiness(state, history)` → 6チェック: サンプル数/勝率/最大DD/MLモデル/Bot稼働/直近週PnL
- 実弾準備スコア: `{score}/{max_score} [████░░]` 形式で週次通知に含める
- 閾値: `READINESS_MIN_TRADES=100`, `READINESS_MIN_WR=0.46`, `READINESS_MAX_DD=-30.0`

#### N. systemd service 更新（--mtf-filter + 9銘柄）

```
ExecStart=...stock_shadow_bot.py --symbols AAPL,MSFT,NVDA,TSLA,QQQ,SPY,AMZN,META,AMD --interval 1h --mtf-filter
```

#### O. 週次 timer に backtest + ML 再学習を追加（`ExecStartPre`）

```
ExecStartPre=...stock_shadow_bot.py --backtest --backtest-days 60
ExecStartPre=...stock_ml_train.py
ExecStart=...stock_shadow_weekly.py --days 7
```

#### P. ダッシュボード ウォッチリスト強化

- `vol_ratio` 列追加: >1.5x=↑緑 / <0.7x=↓赤
- `daily_bull` 列追加: ↑=日足強気 / ↓=弱気 / —=未取得

#### signal_scanner_weekly.py — SIGNAL_ONLY 候補抽出スキャナー（新規）

- **目的**: 資金¥100,000、週10%目標。実注文は絶対禁止（SIGNAL_ONLY mode）
- **対象**: FX 5ペア（USDJPY/EURUSD/GBPJPY/EURJPY/GBPUSD）+ 株8銘柄
- **データ源**: yfinance 一次。IBKR Paper API（localhost:8812）はオプション（未接続時はgraceful skip）
- **エントリー条件**: SMA5>SMA20(BUY) / SMA5<SMA20(SELL) + RSI zone
- **除外**: NO_SUBSCRIPTION_OR_DELAYED_ONLY / spread>0.3% / R:R<1.5 / リスク>¥2000
- **SL/TP**: SL=1×ATR14, TP=2×ATR14 → R:R=2.0
- **ポジションサイジング**: MAX_RISK_PER_TRADE_JPY=¥1000 / (ATR × fx_rate) = 推奨数量
- **信頼スコア 0-100**: トレンドギャップ+20 / RSIゾーン+20 / MA整合+20 / R:R+20 / データ品質+20
- **出力**: 候補ありは `OBSERVE_OK`、候補なしは `OBSERVE_NO_SIGNAL`。`direction_candidate/current_price/spread/volatility/signal_reason/invalidation_price/target_price/risk_reward/max_loss_estimate/confidence/note` を含む JSON+CSV+TXT を `review_out/` に保存し、`note` は `SIGNAL_ONLY_CANDIDATE market=... symbol=... side=...` 形式
- **systemd timer**: 毎週月曜 08:00 JST（`ouroboros-signal-scanner-weekly.timer`）
- **平日自動更新**: 月〜金 09:05 JST に `ouroboros-signal-scanner-daily.timer` で `signal_scanner_weekly.py --dry-run` を実行し、通知なしで候補と `signal_scanner_latest.json` を更新。続けて `signal_scanner_outcome.py` を実行して精度JSONを更新
- **フィードバック学習**: `signal_scanner_outcome.py` は `review_out/signal_scanner_feedback_latest.json` を生成し、`symbol別勝率 / side別勝率 / FX vs STOCK優先度` を次回 `signal_scanner_weekly.py` の confidence に最大 ±15 点で反映する。`FX vs STOCK` の市場優先は各 market_type の closed サンプルが最低 5 件そろった時だけ有効化する
- **ダッシュボード表示**: unified dashboard の `🔍 シグナル候補` では `final confidence / base confidence / feedback補正 / feedback理由` を同時表示し、採点根拠を見返せる。要約欄にも `fx_priority / min_closed_required / closed件数 / market補正 / 理由` を小さく表示する
- **feedback理由の形式**: `symbol:+8 (WR=75.0%, n=4) / side:+4 (WR=57.0%, n=7) / market:+5 (pref=FX)` のように、symbol / side / market の寄与を分解して保存する

```bash
python3 signal_scanner_weekly.py --dry-run       # 通知なし・ローカル保存あり
python3 signal_scanner_weekly.py --fx-only       # FXのみ
python3 signal_scanner_weekly.py --stocks-only   # 株のみ
python3 signal_scanner_weekly.py --interval 4h   # 4時間足
```

#### ファイル（セッション44-45追加・更新）

- `MAIN/stock_shadow_bot.py`（J/K2/L/Q/R 対応: 5特徴量・ntfy通知・MTF・SL・安全機能）
- `MAIN/stock_ml_train.py`（J: 5特徴量・旧CSV補完）
- `MAIN/stock_shadow_weekly.py`（S: 週次勝率履歴・実弾準備スコア完全書き換え）
- `MAIN/tools/unified_dashboard.html`（P: vol_ratio/daily_bull列追加）
- `MAIN/deploy/systemd/ouroboros-stock-shadow.service`（N/R: mtf-filter + 9銘柄）
- `MAIN/deploy/systemd/ouroboros-stock-shadow-weekly.service`（O: ExecStartPre追加）
- `MAIN/signal_scanner_weekly.py`（新規・VM deploy済み）
- `MAIN/deploy/systemd/ouroboros-signal-scanner-weekly.service`（新規・VM有効化済み）
- `MAIN/deploy/systemd/ouroboros-signal-scanner-weekly.timer`（新規・VM有効化済み・月曜08:00 JST）

#### 動作確認（セッション44-45）

- signal_scanner --dry-run: 候補7件（AMZN BUY conf=90% / MSFT BUY conf=90% / EURUSD SELL conf=80% など）
- timer: 次回 `Mon 2026-05-11 08:00:00 JST`
- weekly dry-run: 実弾準備スコア 4/6 [████░░]（サンプル数・MLモデル未達が主因）

最終更新: 2026-05-04 session46 (JST)

### 3-0ZF. 2026-05-04 追加済みロジック（セッション46: T/U/V/W/X/Y 強化バッチ）

#### T. シグナル精度トラッキング（`signal_scanner_outcome.py` 新規）

- 過去の `signal_weekly_*.json` を読み込み、候補の SL/TP 到達を日次クローズで判定
- 結果: `HIT_TP / HIT_SL / OPEN / EXPIRED`（7日超でEXPIRED）
- `review_out/signal_scanner_outcomes.csv` にアップサート保存（既確定行はスキップ）
- 統計サマリー: 勝率(TP/SL)・平均PnL% を表示
- `--ntfy` フラグで ntfy に送信

```bash
python3 signal_scanner_outcome.py           # 全件チェック
python3 signal_scanner_outcome.py --dry-run # 保存なし
python3 signal_scanner_outcome.py --weeks 4 --ntfy
```

#### U. 株シャドウ テイクプロフィット（`stock_shadow_bot.py`）

- `DEFAULT_TP_PCT = 0.04`（エントリー比+4%、SL=-2%と合わせてR:R=2:1）
- `run()` / `run_backtest()` に `tp_pct` パラメータ追加
- TP到達でSELL reason=`TAKE_PROFIT` を発動（HOLD/SMAクロスより優先）
- backtest サマリーに `tp=+4%` 表示追加
- CLI: `--tp-pct 0.04`（0=無効）

#### V. シグナルスキャナー MTF信頼スコアブースト

- `_check_daily_alignment(yf_ticker, signal)` 追加: 日足 SMA5/SMA20 がシグナル方向と一致するか確認
- 一致時に信頼スコア +10（cap=100 は維持）
- 結果に `daily_aligned: true/false/null` フィールドを追加
- `save_results()` が `review_out/signal_scanner_latest.json` も常時上書き保存（Wダッシュボード用）

**効果確認**: AMZN/MSFT が conf=90% → 100% に向上（日足1h同方向）

#### W. ダッシュボード シグナル候補パネル

- SECTIONS に `{id:"scanner", label:"シグナル候補", icon:"🔍"}` 追加
- `fetchOps()` で `signal_scanner_latest.json` を読み込み
- `renderScanner()` / `_renderSignalScannerPanel()` を新規追加
  - サマリーバー: 候補数・リスク合計・利益目標・R:R・スキャン時刻
  - 候補カード一覧: シグナル方向・信頼スコアバー・MTF日足アイコン(↑/↓)・SL/TP/R:R・数量
  - 警告バナー + 実行コマンド表示

#### X. ブレークイーブンSL（`stock_shadow_bot.py`）

- TP距離の50%到達でストップを**エントリー価格（±0）へ移動**
- state.json の position に `stop_price` (更新後) と `breakeven_activated: true` を保存
- 発動後にSLに戻った場合 reason=`BREAKEVEN_SL`（損失なしの損切り）
- `run()` と `run_backtest()` 両方に実装

#### Y. 実弾準備完了 ntfy 通知（`stock_shadow_weekly.py`）

- `readiness.score == max_score (6/6)` かつ `state.live_ready_notified_at` が未設定の場合のみ送信
- Priority=high, Tags=rocket, Title="実弾準備完了 READY_FOR_LIVE"
- 送信後に `live_ready_notified_at` を `stock_shadow_state.json` に保存（重複防止）
- dry-run モードでは発火しない

#### ファイル（セッション46追加・更新）

- `MAIN/signal_scanner_outcome.py`（新規）
- `MAIN/stock_shadow_bot.py`（U/X: TP・ブレークイーブンSL）
- `MAIN/signal_scanner_weekly.py`（V: MTFブースト・latest.json保存）
- `MAIN/stock_shadow_weekly.py`（Y: 実弾準備完了通知）
- `MAIN/tools/unified_dashboard.html`（W: シグナル候補パネル追加）

#### 動作確認

- backtest AAPL 14日: stop=-2% tp=+4% → WR=53.3% PnL=$+12.47
- signal_scanner_outcome --dry-run: 7件 OPEN（スキャン0.2日経過で正常）
- signal_scanner --stocks-only: AMZN/MSFT conf=100%（MTFブースト確認）

---

### 3-0ZI. 2026-05-04 追加済みロジック（セッション49: AI/AJ/AK/AL 拡張バッチ）

#### AI. シグナルスキャナー方向フィルター（`signal_scanner_weekly.py`）

- `scan()` に `direction_filter: Optional[str]` パラメータ追加（`"BUY"` / `"SELL"` / `None`）
- `format_report()` に `direction_filter` 引数追加 → レポートヘッダーに `[ロング候補のみ]` / `[ショート候補のみ]` を表示
- `save_results()` に `direction_filter` 引数追加 → JSONに `direction_filter` フィールドを保存
- CLI: `--long-only`（BUY候補のみ）、`--short-only`（SELL候補のみ）フラグ追加

```bash
python3 signal_scanner_weekly.py --short-only --stocks-only   # ショート候補のみ
python3 signal_scanner_weekly.py --long-only                  # ロング候補のみ
```

#### AJ. stock-shadow systemd に `--both-sides` デフォルト追加

- `deploy/systemd/ouroboros-stock-shadow.service` の ExecStart に `--both-sides` を追加
  - 毎時の shadow paper trading でロング+ショート両方向を自動実行
- `deploy/systemd/ouroboros-stock-shadow-weekly.service` の ExecStartPre（バックテスト）にも `--both-sides` を追加
  - 週次 ML 学習用バックテストもショートを含む両方向データで実施
- 注意: install_systemd_services.sh は stock-shadow を管理しないため、手動で render_unit パターンで /etc/systemd/system/ へコピー・daemon-reload が必要

#### AK. シグナル精度 CSV → ML 学習追加オプション（`stock_ml_train.py`）

- `load_outcome_samples()` 関数追加:
  - `review_out/signal_scanner_outcomes.csv` を読み込み HIT_TP/HIT_SL 行を抽出
  - 対応する `signal_weekly_YYYYMMDD.json` を参照してSMA5/SMA20/RSI14 を取得
  - backtest サンプルと互換の `(X, y)` を返す（インジケーター未取得行はスキップ）
- `--include-outcomes` CLI フラグ追加
  - 有効時: backtest サンプル + outcomes サンプルを合算して学習
  - `signal_scanner_outcomes.csv` が未存在/HIT_TP/HIT_SL なしの場合は警告のみで継続

```bash
python3 stock_ml_train.py --include-outcomes   # バックテスト + シグナル結果を合算学習
```

#### AL. ダッシュボード週次スキャン比較パネル（`unified_dashboard.html` + `signal_scanner_weekly.py`）

- `signal_scanner_weekly.py` に `_update_weekly_history()` 追加:
  - フィルターなし（全方向）スキャン時のみ `review_out/signal_weekly_history.json` を更新
  - 直近4週分のサマリー（date8/total/buy_count/sell_count/avg_confidence/top3）を保存
- ダッシュボード `fetchOpsStatus()` で `signal_weekly_history.json` を取得
- SECTIONS に `{id:"weekly-compare", label:"週次比較", icon:"📅"}` を追加
- `renderWeeklyCompare()` / `_renderWeeklyComparePanel()` を新規追加:
  - 直近4週のサマリーカード（件数・BUY/SELL比率・平均信頼度）
  - 候補件数バースパークライン（SVG）
  - 常連候補テーブル（直近4週のtop3集計で銘柄×登場週数×BUY/SELLバイアス）
- `DASHBOARD_BUILD` を `2026.05.04.1` に更新

#### ファイル（セッション49追加・更新）

- `MAIN/signal_scanner_weekly.py`（AI: --long-only/--short-only フィルター、AL: 週次履歴保存）
- `MAIN/stock_ml_train.py`（AK: load_outcome_samples / --include-outcomes）
- `MAIN/tools/unified_dashboard.html`（AL: 週次比較パネル）
- `MAIN/deploy/systemd/ouroboros-stock-shadow.service`（AJ: --both-sides）
- `MAIN/deploy/systemd/ouroboros-stock-shadow-weekly.service`（AJ: バックテスト --both-sides）

#### 動作確認

- 全ファイルシンタックスチェック（ローカル・VM）: 全OK
- `signal_scanner_weekly --dry-run --short-only --stocks-only`: `[ショート候補のみ]` ヘッダー表示確認
- `signal_scanner_weekly --dry-run`: `signal_weekly_history.json` 生成確認
- `stock_ml_train --include-outcomes`: `No usable samples found` → backtest 12件で正常学習
- systemd: `ouroboros-stock-shadow.service ExecStart` に `--both-sides` 反映確認

---

### 3-0ZH. 2026-05-04 追加済みロジック（セッション48: AE/AF/AG/AH 品質強化バッチ）

#### AE. 週次レポートに PnL 直接集計/推定 内訳表示（`stock_shadow_weekly.py`）

- `compute_weekly_stats()` に `pnl_direct_count` / `pnl_estimated_count` を追加
- SELL行の `pnl_usd` 列に値があれば「直接集計」、なければエントリー/エグジット価格差から「推定」
- AA 実装後のCSVは `pnl_usd` 列を持つため、直接集計件数が増える
- `format_summary()` に `PnL集計: 直接N件 / 推定M件 ✓全件実績値`（M=0時）を表示
- STOP_LOSS に加えて BREAKEVEN_SL も `stop_loss_count` にカウントするよう修正

#### AF. 信頼スコア帯別成績分析 + 閾値調整ヒント（`signal_scanner_outcome.py`）

- `_analyze_by_confidence(all_rows)`: 閉じた結果(HIT_TP/HIT_SL)を conf 帯 `[80-100%/60-79%/<60%]` に分類しWR・avgPnLを計算
- `_confidence_threshold_hint(bands)`: 各帯が5件以上ある場合のみ以下を提案
  - `<60%`帯WR<40% → MIN_CONFIDENCE 60以上を推奨
  - `60-79%`帯WR<45% → MIN_CONFIDENCE 80以上を検討
  - `80-100%`帯WR≥55% → 高信頼度シグナル優先を推奨
- `_format_summary()` にバンド表と 💡 閾値調整ヒントセクションを追加

#### AG. ダッシュボード「シグナル精度」パネル（`unified_dashboard.html`）

- `signal_scanner_outcome.py` が `review_out/signal_scanner_outcomes_latest.json` を保存するよう拡張（`save_outcomes_json()`）
  - フィールド: `generated_at_jst`, `total`, `hit_tp`, `hit_sl`, `open_count`, `expired_count`, `win_rate_pct`, `avg_pnl_pct`, `confidence_bands`, `recent_rows`(最大20件)
- SECTIONS に `{id:"outcome", label:"シグナル精度", icon:"🎯"}` を追加
- `fetchOpsStatus()` で `/review_out/signal_scanner_outcomes_latest.json` を取得
- `renderOutcome()` / `_renderOutcomePanel()` を新規追加:
  - サマリーバー: 勝率(WR)・平均PnL・HIT_TP/SL/OPEN/EXPIRED 件数
  - 信頼帯テーブル(AF連携): band / trades / WR / avgPnL 表示
  - 直近20件テーブル: 銘柄・方向・結果アイコン・PnL%・信頼度・スキャン日

#### AH. ショートサイド対応（`stock_shadow_bot.py`）

- **エントリー条件**: `SMA5 < SMA20 AND RSI > 50` → `sig["action"] = "SHORT"`
- **エグジット条件**: `SMA5 > SMA20 OR RSI < 25` → `sig["action"] = "COVER"`
- **SL/TP（SHORT）**: SL = `entry × (1 + |stop_pct|)`（上方向）、TP = `entry × (1 - tp_pct)`（下方向）
- **ブレークイーブン（SHORT）**: `price ≤ entry × (1 - tp_pct × 0.5)` でストップをエントリーへ移動
- **P&L（SHORT）**: `(entry_price - exit_price) × qty`
- **ログ**: action=`SHORT`（エントリー）/ `COVER`（エグジット）
- `run()` に `both_sides: bool = False` パラメータ追加（デフォルト: ロングのみ）
- `run_backtest()` にも `both_sides` 対応追加（短辺エントリー/エグジット/P&L計算を分岐）
- `_send_trade_notify()` が `"SHORT"` と `"COVER"` を適切な title/body/tags で送信
- CLI: `--both-sides`（デフォルト: 無効 = 従来通り LONG のみ）

```bash
python3 stock_shadow_bot.py --both-sides                           # ロング+ショート両方
python3 stock_shadow_bot.py --backtest --both-sides --symbols TSLA # バックテスト両方向
```

**動作確認**: TSLA 7日バックテスト 片側→14件 / 両方向→21件（SHORT追加確認）

#### ファイル（セッション48追加・更新）

- `MAIN/stock_shadow_bot.py`（AH: SHORT/COVER対応）
- `MAIN/stock_shadow_weekly.py`（AE: pnl_usd直接/推定内訳）
- `MAIN/signal_scanner_outcome.py`（AF: 信頼帯分析・AG: JSON出力）
- `MAIN/tools/unified_dashboard.html`（AG: シグナル精度パネル追加）

#### 動作確認

- 全ファイルシンタックスチェック（ローカル・VM）: 全OK
- `stock_shadow_weekly --dry-run`: `PnL集計: 直接0件 / 推定1件` 表示確認
- `signal_scanner_outcome`: `signal_scanner_outcomes_latest.json` 生成確認（AG）
- バックテスト TSLA 7d `--both-sides`: trades=21（単方向14より増加、SHORT取引追加確認）

---

### 3-0ZG. 2026-05-04 追加済みロジック（セッション47: Z/AA/AB/AC/AD 自動化バッチ）

#### Z. weekly service に outcome 自動実行（`ExecStartPost`）

- `ouroboros-signal-scanner-weekly.service` に `ExecStartPost` を追加
- 毎週月曜 08:00 JST に `signal_scanner_weekly.py` が完了した直後、`signal_scanner_outcome.py --ntfy` を自動実行
- outcome サマリーが ntfy に自動送信される

#### AA. リアル shadow CSV に `pnl_usd` カラム追加（`stock_shadow_bot.py`）

- `CSV_HEADERS` に `pnl_usd` を追加（16→17列）
- SELL時に `net_pnl` を `pnl_usd` として `append_log()` に渡す（BUY/HOLDは `None`）
- バックテスト CSV は元から `pnl_usd` あり。リアル shadow CSV も統一された

#### AB. 前回スキャン比較 NEW/GONE 表示（`signal_scanner_weekly.py`）

- `_load_previous_scan_symbols()`: 今日より古い最新の `signal_weekly_*.json` を読み込み `{symbol: signal}` を返す
- `diff_vs_previous(candidates, prev)`: NEW（今回初登場）/ GONE（前回あったが消えた）を計算
- `format_report()` に `new_symbols` / `gone_symbols` 引数追加
- レポート末尾に「前回比較」セクション表示: `🆕 NEW: AAPL, NVDA` / `❌ GONE: TSLA` 形式

#### AC. ATRベース動的ポジションサイズ（`stock_shadow_bot.py`）

- `_atr14(highs, lows, closes, period=14)`: 本物のTrueRange ATR14 を計算
- `_atr_quantity(risk_per_trade_usd, atr)`: `qty = max(1, floor(risk / ATR14))`
- `_fetch_ohlcv()` が `highs` / `lows` も返すよう拡張
- `run()` に `risk_per_trade` パラメータ追加（default=0.0 = 無効、固定 `--quantity` を使用）
- BUY時: `risk_per_trade > 0` なら ATR取得→サイズ計算→`effective_qty` としてエントリー・ログ
- SELL時: `entry.get("quantity")` で入ったときのサイズを参照（一貫性確保）
- CLI: `--risk-per-trade 10` で「$10リスク = ATR14÷10株」の動的サイジング有効化

```bash
python3 stock_shadow_bot.py --risk-per-trade 10   # 1ATR=$10リスクで自動サイジング
python3 stock_shadow_bot.py                        # 従来通り --quantity 固定
```

#### AD. signal_outcome 日次自動チェック timer（新規）

- `ouroboros-signal-outcome-daily.service` / `.timer` を新規作成・VMにデプロイ
- 毎日 09:00 JST に `signal_scanner_outcome.py --ntfy` を自動実行
- 候補のHIT_TP/HIT_SL状況を毎朝 ntfy で受け取れる
- `review_out/signal_outcome_systemd.out.log` / `.err.log` にログ保存

#### ファイル（セッション47追加・更新）

- `MAIN/stock_shadow_bot.py`（AA: pnl_usd CSV・AC: ATRサイジング）
- `MAIN/signal_scanner_weekly.py`（AB: 前回スキャン比較）
- `MAIN/deploy/systemd/ouroboros-signal-scanner-weekly.service`（Z: ExecStartPost追加）
- `MAIN/deploy/systemd/ouroboros-signal-outcome-daily.service`（AD: 新規）
- `MAIN/deploy/systemd/ouroboros-signal-outcome-daily.timer`（AD: 新規）

#### 動作確認

- 全ファイルシンタックスチェック（ローカル・VM）: 全OK
- `signal_scanner_outcome --dry-run` on VM: AMZN/MSFT OPEN 2件（正常）
- `stock_shadow_bot --backtest --backtest-days 7 AAPL`: WR=54% PnL=$+13.00（正常）
- timers: outcome-daily → 2026-05-05 09:00 JST / scanner-weekly → 2026-05-11 08:00 JST

---

### 3-0ZC. 2026-05-04 追加済みロジック（セッション42: シャドウ bot 強化 A〜D）

#### A. 1時間足シグナル（`--interval 1h` デフォルト）

- `_fetch_closes()` が `interval` 引数を受け取るよう変更（`"1h"` または `"1d"`）
- デフォルト `DEFAULT_INTERVAL = "1h"` でサンプル収集速度を 10×改善（30分ごとの systemd 起動で 1日あたり最大 18回チェック）
- systemd service の ExecStart に `--interval 1h` 追加、VM 側 daemon-reload 済み

#### B. HOLD 記録（ネガティブサンプル蓄積）

- BUY/SELL 以外の HOLD も CSV に記録（`order_status=HOLD_LOG`）
- ML 学習時に「シグナルなし」の例として活用可能
- `--no-hold-log` フラグで無効化可能

#### C. バックテストモード（`--backtest`）

```bash
python3 stock_shadow_bot.py --backtest                          # 直近30日
python3 stock_shadow_bot.py --backtest --backtest-days 60 --interval 1h
python3 stock_shadow_bot.py --backtest --symbols AAPL,NVDA,QQQ --interval 1d
```
- 出力: `review_out/backtest_YYYYMMDD_{interval}.csv`（BUY/SELL + pnl_usd 列）
- サマリー: 総トレード数・勝率・累積 PnL を標準出力

#### D. ダッシュボード統合（日次 PnL 棒グラフ）

- `stock_shadow_state.json` に `daily_pnl_usd: {"2026-05-04": -0.03}` を追記
- `_renderShadowPanel()` に直近 7 日の PnL 棒グラフを追加（USD、正=緑/負=赤）
- interval ラベル（1h / 1d）をパネルタイトルに表示

#### 動作確認（セッション42）
```
[backtest] interval=1h  days=14  symbols=['NVDA', 'QQQ', 'SPY']
  [NVDA] trades=14  wins=7  WR=50%  PnL=$-6.56
  [QQQ]  trades=16  wins=7  WR=44%  PnL=$+15.72
  [SPY]  trades=14  wins=4  WR=29%  PnL=$-2.90
[backtest] TOTAL  trades=44  wins=18  WR=40.9%  PnL=$+6.26
```
- dry-run: NVDA SELL (SMA5_CROSS_DOWN 1h), AAPL/QQQ HOLD → CSV に HOLD_LOG 記録済み
- state.json に `daily_pnl_usd` と `interval` フィールド追加確認済み

---

### 3-0ZB. 2026-05-04 追加済みロジック（セッション41: 株シャドウ取引・自動スナップショット）

#### 1. `stock_shadow_bot.py` 新規作成（シャドウ取引）

- yfinance（無料）で OHLCV 取得、SMA5/SMA20 + RSI(14) シグナル生成
- デフォルト: dry-run（シグナル表示のみ）
- `--execute` フラグ: ibkr_paper_api.py `/order` 経由でペーパー注文
- 状態: `review_out/stock_shadow_state.json`（open positions, 累積P&L, 総トレード数）
- ログ: `review_out/stock_shadow_YYYYMMDD.csv`（ML用サンプル: 価格・指標・シグナル・約定状況）
- エントリー条件: SMA5 > SMA20 AND RSI < 65
- イグジット条件: SMA5 < SMA20 OR RSI > 75

```bash
python3 stock_shadow_bot.py                     # dry-run (1h bar)
python3 stock_shadow_bot.py --execute           # ペーパー注文実行（ibkr_paper_api.py 起動が必要）
python3 stock_shadow_bot.py --symbols AAPL,NVDA
```

#### 2. `tools/run_ibkr_snapshot.sh` 新規作成

- 米国市場時間（JST 22:00〜7:00）のみ実行するラッパースクリプト
- launchd から呼ばれる

#### 3. `tools/com.ouroboros.ibkr_snapshot.plist` 新規作成

- 5分ごとに run_ibkr_snapshot.sh を実行する launchd ジョブ

**インストール手順:**
```bash
cp MAIN/tools/com.ouroboros.ibkr_snapshot.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.ouroboros.ibkr_snapshot.plist
# 確認:
launchctl list | grep ouroboros
# 停止:
launchctl unload ~/Library/LaunchAgents/com.ouroboros.ibkr_snapshot.plist
```

#### 4. `ibkr_paper_api.py` / `test_ibkr_connection.py` — A2 USDJPY close フォールバック

- `_fx_mp` 抽出順を拡張: `market_price → last → bid → reference_price → close`
- 市場クローズ中（BID_ASK_UNAVAILABLE）でも close を fx_rate として使用可能に

#### 5. `tools/unified_dashboard.html` — A3 表示改善 + シャドウパネル

- USD/JPY カード: bid/ask 取得時は `156.865 / 156.875` 表示、status も反映
- `fetchOpsStatus()` に `stock_shadow_state.json` 読み込み追加
- `_renderShadowPanel()` 関数追加: オープンポジション・累積PnL・最終実行時刻・使い方を表示

#### ファイル
- `MAIN/stock_shadow_bot.py`（新規）
- `MAIN/tools/run_ibkr_snapshot.sh`（新規）
- `MAIN/tools/com.ouroboros.ibkr_snapshot.plist`（新規・Mac launchd インストール済み）
- `MAIN/deploy/systemd/ouroboros-stock-shadow.service`（新規・VM systemd 有効化済み）
- `MAIN/deploy/systemd/ouroboros-stock-shadow.timer`（新規・VM systemd 有効化済み・JST 22:00-07:00 / 30分ごと）
- `MAIN/ibkr_paper_api.py`（A2修正）
- `MAIN/test_ibkr_connection.py`（A2修正）
- `MAIN/tools/unified_dashboard.html`（VM deploy済み）

#### 動作確認
- Mac: `launchctl list | grep ouroboros.ibkr_snapshot` → `0` = 待機中（5分ごと、JST 22-7時のみ実行）
- VM: `systemctl list-timers ouroboros-stock-shadow.timer` → 次回 JST 22:00 実行予定
- `stock_shadow_bot.py` dry-run 結果: NVDA BUY シグナル確認済み（SMA5=207 > SMA20=197, RSI=58.1）

### 3-0ZB. 2026-05-05 保守点検（セッション41: ダッシュボードアクセス修正・パラメータ整合）

#### 修正内容

1. **ダッシュボードアクセス（port 8080→8787）**
   - port 8080 は cloud security group でブロックされており外部から開けない
   - `widget_status.py`: `/unified_dashboard.html`, `/dashboard` ルートを認証チェック前に移動
   - → `http://161.33.26.35:8787/unified_dashboard.html` で認証不要でアクセス可能

2. **CONTROL.csv パラメータ修正**
   - `ai_threshold`: 0.7 → 0.73（CLAUDE.md 仕様との不一致解消）
   - `ai_veto_threshold`: 0.8 → 0.30（CLAUDE.md 仕様との不一致解消）

3. **unified_dashboard.html 修正**
   - `fetchLocalJson`: `http://` で開いた場合もトークンを Authorization ヘッダーで送信するよう修正
   - `?token=TOKEN` URL パラメータから自動で localStorage に保存する機能追加
   - 設定パネルにブックマーク用 URL 表示・コピーボタン追加
   - DASHBOARD_BUILD = "2026.05.05.1"

4. **.ops_checks.json クリーンアップ**
   - ローカル Mac パス (`/Users/tani/...`) を持つ古いエントリ2件を削除
   - (`trade_event_notifier`, `start_shadow_paper.sh` — 2月〜3月の stale エントリ)

#### ダッシュボードアクセス URL

```
http://161.33.26.35:8787/unified_dashboard.html
# または（初回トークン自動保存）:
http://161.33.26.35:8787/unified_dashboard.html?token=i27jMAuteMA-5EO2ihKMsilEHPROSZ63
```

#### ファイル
- `MAIN/tools/widget_status.py`（ダッシュボードルートを認証前に移動、VM deploy済み）
- `MAIN/tools/unified_dashboard.html`（fetchLocalJson修正・?token= サポート・ブックマークURL、VM deploy済み）
- `MAIN/CONTROL.csv`（ai_threshold=0.73, ai_veto_threshold=0.30、VM deploy済み）
- `MAIN/.ops_checks.json`（stale エントリ削除、VM更新済み）

---

### 3-0ZA. 2026-05-04 追加済みロジック（セッション40: FX→JPY P&L換算）

#### 背景
FX USDJPY delayed データ取得成功（bid=156.865, ask=156.875, market_price=156.87）により、
USD建てポジション（NVDA等）の含み損益をJPY換算して表示できるようになった。

#### 1. `ibkr_adapter.py` — `enrich_positions_pnl()` fx_rate 引数追加

- `fx_rate: Optional[float] = None` 引数追加
- USD通貨ポジションに `unrealized_pnl_calc_jpy = round(pnl_usd * fx_rate, 0)` を付加
- fx_rate が None または通貨が USD 以外の場合は `unrealized_pnl_calc_jpy = None`

#### 2. `ibkr_paper_api.py` — FX rate 抽出・渡す

- `/snapshot` ハンドラ: `fx.market_price`（優先）→ `last` → `bid` を fx_rate として抽出
- `enrich_positions_pnl(positions, snapshots, fx_rate=fx_rate)` に変更

#### 3. `test_ibkr_connection.py` — FX rate 抽出・渡す

- `Optional` import 追加
- `fx_snapshot` から fx_rate を抽出し `enrich_positions_pnl(... fx_rate=_fx_rate)` に変更

#### 4. `tools/unified_dashboard.html` — ポジションテーブル JPY 列追加

- テーブルヘッダー: 「含み損益(参考)」→「含み損益(USD)」「含み損益(JPY)」に変更（7列）
- `pnlJpyHtml`: `unrealized_pnl_calc_jpy` を `¥` 表示（+/- カラーコード、参考ラベル付き）
- `colspan="6"` → `colspan="7"` 更新
- VM deploy済み（tools/ 正パスへ）

#### ファイル
- `MAIN/ibkr_adapter.py`（fx_rate 引数・JPY換算フィールド）
- `MAIN/test_ibkr_connection.py`（fx_rate 抽出・渡す）
- `MAIN/ibkr_paper_api.py`（fx_rate 抽出・渡す）
- `MAIN/tools/unified_dashboard.html`（VM deploy済み）

### 3-0Z. 2026-05-03 追加済みロジック（セッション37: IBKR 遅延データ対応・Dashboard表示改善）

#### 背景
test_ibkr_connection.py 実行で接続成功・口座情報・ポジション取得成功を確認。
株価は Error 10089（マーケットデータ購読不足）、FXは bid/ask=-1.0・close取得のみ。
これらを異常終了扱いにせず、状態を明示する形に改善。

#### 1. `ibkr_adapter.py` — 遅延データ対応・ステータス細分化

- `_MDT_MAP` 定数追加: `{"live":1, "frozen":2, "delayed":3, "delayed_frozen":4}`
- `IBKRAdapter` に `market_data_type: str = "delayed"` フィールド追加
- `connect()`: 接続後に `self._ib.reqMarketDataType(mdt)` を自動呼び出し
- `_snapshot()` ステータス分類を強化:
  - `LIVE_OK` / `DELAYED_OK` — 有効価格取得成功
  - `BID_ASK_UNAVAILABLE` — close のみ（reference_only=True, reference_price=close）
  - `PRICE_UNAVAILABLE` — 価格なし（Error 10089 等）
  - `ERROR` — get_stock_snapshots() の per-symbol try/except で補足
- `reference_only` / `reference_price` フィールドを追加
- `enrich_positions_pnl(positions, stock_snapshots)` モジュール関数を追加:
  - pnl_calc_status: OK | REFERENCE_ONLY | PRICE_UNAVAILABLE | NO_SNAPSHOT
  - unrealized_pnl_calc / pnl_current_price をポジションに付加

#### 2. `test_ibkr_connection.py` — MDT引数・PnL強化

- `--market-data-type` 引数追加（default: "delayed"）
- `market_data_mode` をJSONペイロードに追加
- `enrich_positions_pnl()` 呼び出しでポジションにPnLフィールドを付加

#### 3. `ibkr_paper_api.py` — MDT対応・PnL付加

- `_CFG["market_data_type"] = "delayed"` 追加
- `_make_adapter()` に `market_data_type` を渡すよう変更
- `--market-data-type` 引数追加
- `/snapshot` レスポンスに `market_data_mode` 追加、`enrich_positions_pnl()` 呼び出し

#### 4. `tools/unified_dashboard.html` — 価格表示改善

- `stockPriceHtml(sym)` 関数追加:
  - `DELAYED_OK` → 価格 + "遅延"ラベル
  - `reference_only` → "参考 $xxx"
  - `PRICE_UNAVAILABLE` → "価格なし"
  - `BID_ASK_UNAVAILABLE` → "Bid/Askなし"
  - `NO_SUBSCRIPTION_OR_DELAYED_ONLY` → "購読なし"
- ウォッチリスト行を `stockPriceHtml()` に切り替え
- スナップショットカードに `AAPL status` / `USDJPY close` / `USDJPY status` 行追加
- ポジションテーブルに「含み損益(参考)」列追加（pnl_calc_status付き）
- VM: dashboard deploy済み

#### ファイル
- `MAIN/ibkr_adapter.py`（MDT・ステータス・PnL enrich）
- `MAIN/test_ibkr_connection.py`（MDT引数・PnL）
- `MAIN/ibkr_paper_api.py`（MDT対応）
- `MAIN/tools/unified_dashboard.html`（VM deploy済み）

### 3-10. 2026-05-05 追加済みロジック（セッション38: Fib改善バッチ F/G/H/I）

#### 背景
セッション37の追加提案 F・G・H・I を実装。streak stop Fib例外/ポジション保有中Fibリアルタイム更新/Fibコンボ集計ツール/weekly-autotrain連携。

#### F. weekly-autotrain.service に stock_shadow_wr_update.py 追加

- `deploy/systemd/ouroboros-weekly-autotrain.service` に ExecStartPost を追加
- 毎週月曜の自動学習後に取引ベース WR を自動リフレッシュ

#### G. fib_zone → AI 学習ログ記録 + `tools/fib_combo_report.py` 新規作成

- `AI_TRAIN_FIELDS` に `fib_zone` / `fib_wave3_candidate` / `aiba_aligned` 追加
- `open_pos_new` にこれら3フィールドを保存（entry 時）
- `_append_ai_training_trade_from_exit_row` の out_row に同フィールド追加
- `tools/fib_combo_report.py`: 学習ログの fib_zone セグメント別 WR を集計・表示
  - Usage: `python3 tools/fib_combo_report.py [--days N] [--live-only]`
  - GOLDEN+AIBA_combo / GOLDEN(no_aiba) / REVERSAL / その他を分離表示

#### H. ポジション保有中の `_fib_last` リアルタイム更新

- extend チェック時（ai_dp_extend）: build_features 後に `_fib_last` を更新
- exit 管理ループ: 5分おきに軽量 fib 再計算して `_fib_last` を更新
  - `get_ohlc_bars → extract_swing_points → calc_fibonacci_retracement_snapshot`
  - ダッシュボードの Fib Zone 表示がポジション保有中も刷新される

#### I. streak stop Fib 黄金地帯例外

- streak stop 発動時、`_fib_last.zone == "GOLDEN"` かつ更新から10分以内なら例外的にエントリー許可
- ai_note に `fib_golden_exception=1` を記録
- entry_flow 本体の流れ変更なし（`_fib_last` 読み取りのみ）
- CONTROL.csv 変更不要（`fib_retracement_enabled` が既存の gate）

#### バージョン
- OUROBOROS_BOT_VERSION: 2026.05.05.2 → 2026.05.05.3

#### ファイル
- `MAIN/bot.py` (streak Fib例外 + _fib_last保有中更新 + fib学習ログフィールド)
- `MAIN/tools/fib_combo_report.py` (新規)
- `MAIN/deploy/systemd/ouroboros-weekly-autotrain.service` (ExecStartPost追加)

### 3-0Z. 2026-05-05 追加済みロジック（セッション37: Fib×AIBAコンボ・Fibゾーン表示・株式取引WR）

#### 背景
前回セッション（session36〜）の追加提案 B・D・E を実装。Fib黄金地帯+AIBA整合のコンボブースト、
ダッシュボードへのFibゾーンリアルタイム表示、株式シャドーの取引ベースWR集計を追加。

#### 1. `bot.py` — Fib × AIBA コンボブースト追加

- `FIB_AIBA_COMBO_BOOST_DEFAULT = 0.08` 定数追加
- `fib_aiba_combo_boost` config フィールド + CONTROL.csv パース追加
- AIスコア計算: `fib_wave3_candidate AND aiba_aligned` の両方が True 時に `comps["fib_aiba_combo"] = +0.08` 追加
  - Fib単体(+0.18)、AIBA単体(+0.10)に加えてコンボ時はさらに+0.08
- エントリー評価時に `_fib_last` を state.json に保存（ダッシュボード表示用）
  - zone / wave3_candidate / retrace_pct / swing_range_pct / side / updated_at_jst
- ai_note に `fib_comp` / `fib_aiba_combo_comp` を記録

#### 2. `tools/widget_status.py` — `fib_last` フィールド追加

- state.json の `_fib_last` を `fib_last` として API レスポンスに追加

#### 3. `tools/unified_dashboard.html` — Fib ゾーン表示

- マーケットフェーズカードに Fib Zone セクションを追加
  - GOLDEN = 緑・🌟、REVERSAL = 赤、DEEP = 橙
  - retrace_pct / 評価サイド / 更新時刻 を表示
- 米国株シャドーカードの「取引日 WR」→「取引 WR (TP/SL)」に変更
  - `trade_wr_pct` / `trade_wr_n` / `trade_wr_wins` を使用（日次ベースより正確）

#### 4. `tools/stock_shadow_wr_update.py` — 取引ベース WR 集計スクリプト（新規）

- `backtest_*.csv` の SELL/COVER 行から pnl_usd を集計
- `stock_shadow_state.json` に `trade_wr_pct` / `trade_wr_n` / `trade_wr_wins` / `weekly_trade_stats` を書き戻す
- 現在: 24件 WR=45.8% PnL=$10.41 (2026-W09〜W18)
- 使用: `python3 tools/stock_shadow_wr_update.py` (または `--print` でstate非更新)

#### バージョン
- OUROBOROS_BOT_VERSION: 2026.05.05.1 → 2026.05.05.2

#### ファイル
- `MAIN/bot.py`（Fib×AIBAコンボ + _fib_last保存）
- `MAIN/tools/widget_status.py`（fib_last追加）
- `MAIN/tools/unified_dashboard.html`（Fibゾーン表示 + 取引WR）
- `MAIN/tools/stock_shadow_wr_update.py`（新規）

### 3-0Y. 2026-05-03 追加済みロジック（セッション36: IBKR株式ペーパートレード実装）

#### 背景
IBKR Paper Trading 口座を作成。既存の読み取り専用 ibkr_adapter.py を拡張し、
ペーパー注文の送信・管理・キャンセルができるようにした。

#### 1. `ibkr_adapter.py` — 注文メソッド追加

- `place_order(symbol, action, quantity, order_type, limit_price, ...)` → 成行/指値注文送信
- `get_open_orders()` → 未約定注文一覧
- `get_trades()` → 本日約定履歴（fills）
- `cancel_order(order_id)` → 注文キャンセル
- 対応するモジュールレベル関数も追加
- 注意: `readonly=False` のアダプターが必要。読み取り専用の既存テストは readonly=True のまま。

#### 2. `ibkr_paper_api.py` — ペーパー注文 HTTP API サーバー（新規）

- `python3 ibkr_paper_api.py` で起動（localhost:8812）
- 接続先: TWS Paper Trading、localhost:7497
- エンドポイント:
  - `GET /health` — 接続状態確認
  - `GET /snapshot` — 口座サマリー+ポジション+株価取得（review_out/ibkr_connection_*.json も更新）
  - `POST /order` — ペーパー注文送信 `{symbol, action, quantity, order_type, limit_price}`
  - `GET /orders` — 今日の注文ログ（review_out/paper_orders_YYYYMMDD.json）
  - `POST /cancel` — 注文キャンセル
  - `GET /trades` — 約定履歴
- CORS対応（ダッシュボードからの呼び出し可能）
- クライアントID: RO=19, RW=18（test=1, readonly=17と競合なし）

#### 3. `tools/unified_dashboard.html` — 株式タブにペーパー注文UIを追加

- `_renderPaperTradingPanel()` 関数追加: 株式タブ末尾に表示
  - Paper API状態（localhost:8812へのhealth check）
  - 注文フォーム: 銘柄・数量・BUY/SELL・成行/指値・🔄更新
  - 指値選択時のみ価格入力欄が表示（`toggleLimitInput()`）
  - 注文結果のインライン表示（state.paperResult）
  - 今日の注文一覧テーブル（直近10件）
- `fetchPaperApi()` — /health + /orders を同時取得
- 株式タブ切り替え時に自動fetchPaperApi()
- `refresh()` に stocks タブ時の fetchPaperApi 追加
- VM: dashboard deploy済み

#### 使用方法（ローカルMac）
1. TWS または IB Gateway を Paper Trading で起動
   - API設定: Socket Port=7497、Read-Only API=OFF
2. `python3 /path/to/MAIN/ibkr_paper_api.py` を起動
3. ダッシュボード「株式」タブ → 「🔄 更新」でスナップショット取得
4. 注文フォームから BUY/SELL 送信

#### ファイル
- `MAIN/ibkr_adapter.py`（注文メソッド追加）
- `MAIN/ibkr_paper_api.py`（新規）
- `MAIN/tools/unified_dashboard.html`（VM deploy済み）

### 3-0X. 2026-05-03 追加済みロジック（セッション35: Symphony発想・市場復帰通知強化・週次休止日数）

#### 背景
OpenAI Symphony（複数AIエージェント自動オーケストレーション）の発想を応用。
「条件を監視し、変化時に自動で適切なアクションを起こす」= 市場フェーズ変化検知 → 自動通知。

#### 1. trade_event_notifier.py: B→A/C 市場復帰通知強化

- **背景**: phase B→A/C（choppy→trending）転換時にエントリー再開可能だが、既存通知は汎用「局面転換」のみ。
- **変更**: `market_phase_changed` ブロック内で `phase_prev_cursor == "B" and phase_now in ("A", "C")` を検知。
  - `is_resume=True` 時: タイトル「Ouroboros 市場復帰 エントリー再開可能」、テキストに「エントリー再開可能 (phase B終了)」追加。
  - ntfy: `tags="green_circle"`, `priority="high"` で強調送信。
  - `payload["event"]` = `"market_phase_resume"` （ログで判別可能）。
  - それ以外の転換: 従来通り「局面転換」。
- **VM deploy**: 完了（trade_event_notifier.timerが1分ごと実行のため再起動不要）。

#### 2. send_weekly_summary_ntfy.py: 休止日数追加

- **背景**: OBSERVE_OK=0 日が続いても週次サマリーに反映されず、ユーザーが状況把握しにくかった。
- **変更**: `_count_dormant_days(lookback_days=21)` 関数を追加。
  - 今日から遡り、OBSERVE_OK=0 の連続日数と最終OBSERVE_OK日付を返す。
  - 3日以上で行追加: `📭 休止継続N日 (最終OBSERVE_OK: YYYY/MM/DD)`
  - 7日以上で `⚠️` アイコンに変化。
- **VM確認**: `python3 tools/send_weekly_summary_ntfy.py` → `⚠️ 休止継続9日 (最終OBSERVE_OK: 2026/04/24)` 正常出力・ntfy送信成功。

#### 影響ファイル
- `tools/trade_event_notifier.py`（VM deploy済み）
- `tools/send_weekly_summary_ntfy.py`（VM deploy済み）

### 3-0W. 2026-05-03 追加済みロジック（セッション34: /status MR PAPER統合・OBSERVE_OK=0監視・ログ分析）

#### 1. .claude/commands/status.md: MR PAPER(7日)セクション追加

- **背景**: 毎朝の/statusにMR PAPERの状況が表示されないため、昇格判断材料が不足していた。
- **変更**: 直近7日 WR推移の後に `🎯 MR PAPER (7日)` セクションを追加。
  - `mr_observe_summary.build_multi_day_summary()` を直接インポートして7日分を集計。
  - 表示: `entries=N  TP=X SL=Y TIMEOUT=Z  WR=W%` + `rank_A=N trigger_n=T reclaim_n=R`
  - エラー時は `⚪ MR PAPER取得エラー: <msg>` にフォールバック。
- **変更2**: 直近7日ループに `obs_ok_d` カウントを追加。OBSERVE_OKがあった日は行末に `OK=N` を表示。
- **変更3**: 総合判定に `obs_ok_days_7 == 0` チェック追加 → `7日連続OBSERVE_OK=0(EM休止中)` を issues に追加。

#### 2. 7日間ログ分析（2026-05-03 実施）

- **OBSERVE_OK=0継続の原因特定**: 2026-04-04以降、OBSERVE_OKが完全にゼロ。
  - 主因1: `OBSERVE_BUY/SELL_FAST_MA_NEAR` が22〜27件/日ブロック（buy_fast_ma_distance_pct=0.08%）。
  - 主因2: `OBSERVE_TREND_STRENGTH_WEAK` が4〜5件/日ブロック（ER < 0.30）。
  - 市場フェーズ: phase=B（MA_FLAT）、ER=0.004 → レンジ相場で正常動作。
- **最後のOBSERVE_OK（実注文）**: 2026-04-03 16:33 BUY_CANDIDATE `entry_unfilled exec=LIVE`。
- **5/2, 5/3 取引ゼロの理由**: 市場choppy状態継続、ボット正常動作。
- **MR PAPER実績 (7日)**: entries=3, TP=3, SL=0, WR=100%。

#### 影響ファイル
- `.claude/commands/status.md`（ローカルMacのみ、VMデプロイ不要）

最終更新: 2026-05-03 session34 (JST)

---

### 3-0O. 2026-04-29 追加済みロジック（セッション25: 追加改善バッチ）

#### BOT_VERSION 管理開始（後にsession29で廃止・OUROBOROS_BOT_VERSIONに統一）
- `bot.py` 冒頭に `BOT_VERSION = "1.25.0"` 追加（session24: is_shadow追加）
- バージョン命名規則: `1.<major>.<minor>`。今後の変更はこのバージョンを更新すること

#### スマート出口条件緩和
- **`CONTROL.csv`** VM + Local: `no_follow_through_exit_max_current_fav_pct`: `0.00` → `0.02`
- 変更理由: 60日間で発動0件。`0.00` は「完全損益分岐点以下でないと発動しない」という過度に厳しい条件
- SIGHUP済み（PID 147245）

#### 10h AIブロック率 再評価（session25 時点）
- **block_avg_score=0.605 + boost(+0.10) = 0.705 < 閾値0.73**
- 根本原因: モデルの素点が低い（設定問題ではなく学習問題）
- 13h: `ai_score_bad_hours` 削除後に pass_rate=100% に改善（設定修正は有効だった）
- 10h対応案: `ai_threshold` を 0.73→0.70 に下げるか、`ai_time_good_hour_boost` を 0.10→0.13 に上げるか要検討

#### smart_exit_report 週次自動送信
- `ouroboros-weekly-autotrain.service`: ExecStartPost に `smart_exit_report.py --days 7 --ntfy` 追加
- 月曜00:20の週次自動学習後にスマート出口の週次効果レポートをntfy送信

#### Shadow A/B 状態確認
- Main ai_training_log: is_shadow=0 で書き込み確認済み（143行 + 今後の新規取引）
- Shadow ai_training_log: ヘッダー作成済み（is_shadow列あり）。Shadow取引が完了次第 is_shadow=1 で蓄積開始
- Shadow logs: `/home/ubuntu/trading_bot/logs/instances/shadow/ai_training_log.csv`

#### 影響ファイル（このバッチ）
- `MAIN/bot.py`（BOT_VERSION=1.25.0 追加 + is_shadow記録、VM再デプロイ済み）
- `MAIN/CONTROL.csv`（no_follow_through_exit_max_current_fav_pct: 0.00→0.02）
- `/etc/systemd/system/ouroboros-weekly-autotrain.service`（smart_exit_report ExecStartPost追加）

最終更新: 2026-04-29 session25 (JST)

---

### 3-0K. 2026-04-26 追加済みロジック（セッション14: エージェント管理・バージョン追跡・KEIBA週次WR）

#### エージェントマネージャー（/manage）

- **`.claude/commands/manage.md`** 新規作成: 全スキルの台帳管理ファイル
  - 12スキルの担当領域・入力データ・出力を一覧化（重複なし確認済み）
  - データソース別担当エージェントマトリクス（重複検出付き）
  - 統合・廃止・新設ルールと重複スキャン用 Python スクリプト内蔵

#### バージョントラッカー（/version）

- **`.claude/commands/version.md`** 新規作成: バージョン確認・記録の必須手順
  - Step 1: 変更前バージョン確認（bot.py / dashboard.py / widget_status.py）
  - Step 2: 変更後スペック表更新手順（ヘッダー行 + 実装状況テーブル）
  - Step 3: 整合性チェック（実体 vs HANDOVER.json vs スペック表）
  - バージョン番号フォーマット定義と変更不要なケースを明記

#### CLAUDE.md 品質基準強化

- スキルマップに `/manage`・`/version` を「管理系」として追加
- Output Gate に 2 ルール追加:
  - **コード変更前に `/version` で現バージョン確認**
  - **変更後に `/version` で整合性チェック**
- スペック表（`OUROBOROS_TRADING_SPEC_TABLE.md`）更新を必須化
- 新規システム追加手順に「`/manage` 台帳追加」を明記

#### KEIBA 週次WR delta 通知

- **`KEIBA/keiba_auto_cycle.py`**: `_notify_wr_delta_if_needed()` 追加
  - 直近20件 vs 前20件の WR を比較（≥ ±5%pt で通知）
  - ≥10%pt は Priority=high、重複通知防止付き

#### /ai スキル週次WR時系列追加

- **`.claude/commands/ai.md`**: セクション6「週次WR時系列（直近4週）」を追加

#### 影響ファイル（このバッチ）
- `.claude/commands/manage.md`（新規）
- `.claude/commands/version.md`（新規）
- `CLAUDE.md`（品質基準強化・スキルマップ更新）
- `KEIBA/keiba_auto_cycle.py`（週次WR delta ntfy追加）
- `.claude/commands/ai.md`（週次WR時系列セクション追加）

最終更新: 2026-04-26 session14 (JST)

---

### 3-0J. 2026-04-26 追加済みロジック（セッション13: KEIBA ntfy 連携・/status KEIBA 組み込み）

#### KEIBA ntfy 通知連携

- **`KEIBA/keiba_auto_cycle.py`** に ntfy 送信ヘルパーを追加:
  - `_read_ntfy_url()`: `auto_cycle_config.json` の `ntfy_url` キーを優先し、未設定なら MAIN の `secrets.toml` の `ntfy_topic_url` にフォールバック。いずれも空なら送信スキップ
  - `_send_keiba_ntfy(title, body, *, priority, tags)`: ntfy に POST。失敗は黙って無視（サイレント）
  - **有効化方法**: `KEIBA/data/auto_cycle_config.json` に `"ntfy_url": "https://ntfy.sh/<YOUR_TOPIC>"` を追加するだけ
- **通知タイミング**:
  - 週次予想が新規生成されたとき（`skipped=False`）→ `🐎 KEIBA 予想完了` / 今週レース数 + 1着的中率を送信
  - 自動サイクルが例外で失敗したとき → `🐎 KEIBA エラー` / Priority=high / Tags=warning

#### `/status` への KEIBA 組み込み

- **`.claude/commands/status.md`** 更新: SSH ブロックの直後にローカル Python ブロックを追加
  - `KEIBA/data/auto_cycle_status.json` を読み取り稼働状態・最終完了時刻・成功/失敗を表示
  - `KEIBA/data/prediction_feedback.csv` から 1着的中率を計算して表示
  - アイコン: 🟢（正常停止）/ 🔴（失敗）/ 🟡（実行中）、的中率 ≥50%=🟢 / ≥35%=🟡 / <35%=🔴

#### Shadow A/B テスト中間評価スケジュール（2026-05-02）

- `shadow_ab_compare.py --since 2026-04-25` で MAIN（0.08）vs Shadow（0.06）を比較
- CronCreate で 2026-05-02 10:03 JST に one-shot エージェントを登録済み（セッション内有効）
- 評価基準:
  - Shadow WR ≥ MAIN+5%pt → Shadow 優勢: MAIN を 0.06 に変更提案
  - 差 <5%pt または trades<10 → 2週間後に再評価
  - Shadow WR < MAIN−3%pt → 0.06 は劣勢: Shadow を 0.08 に戻すことを提案

#### 影響ファイル（このバッチ）
- `KEIBA/keiba_auto_cycle.py`（ntfy 送信ヘルパー追加、成功/エラー通知）
- `.claude/commands/status.md`（KEIBA ローカル状態ブロック追加）

最終更新: 2026-04-26 session13 (JST)

---

### 3-0F. 2026-04-25 追加済みロジック（セッション10: A/Bテスト・パラメータ最適化）

#### Shadow A/Bテスト評価ツール
- **`tools/shadow_ab_compare.py`** 新規作成: MAIN（buy_fast_ma=0.08）vs Shadow（0.06）を並べて比較
  - WR、PF、fast_ma_near ブロック率、日次内訳を並列表示
  - サンプル数 < 5 件の場合は「データ不足」と判定して誤判断を防止
  - 既定 since=2026-04-25（A/B テスト開始日）
- **`.claude/commands/filter.md`**: section 5「Shadow A/Bテスト比較」を追加

#### バックテストTP/SLパラメータスイープ
- **`tools/run_backtest.py`** に `--sweep` フラグを追加
  - TP候補 [0.160, 0.180, 0.190, 0.200, 0.220] × SL候補 [0.110, 0.120, 0.130, 0.140, 0.160] の 25 組を dry-run で一括実行
  - PF降順で結果テーブルを表示し、最良の組み合わせを推奨
  - オーバーフィット注意: 改善幅 < 0.05 PF の場合は現行維持を推奨するメッセージを付記
- **`.claude/commands/backtest.md`**: 「パラメータ最適化: TP/SL スイープ」セクション追加

#### CONTROL修正（VM）
- `ai_train_weekly_bad_hours` が空欄だったため `"14,15,16"` に設定

#### 提案Aの検証結果
- `bot.py` の `_compute_sample_weight()` (line 5288) で `ai_train_weekly_bad_hours` を正しく読み込み、0.70 倍の重みを適用する実装が確認済み
- `ai_model.json` の `auto_train_weekly_bad_hours` は次回 auto-train 実行後に記録される（現時点は初回学習待ち）

#### 影響ファイル（このバッチ）
- `MAIN/tools/shadow_ab_compare.py`（新規）
- `MAIN/tools/run_backtest.py`（`--sweep` モード追加、`avg_ret` 返値追加）
- `.claude/commands/filter.md`（Shadow A/B比較 section 5 追加）
- `.claude/commands/backtest.md`（パラメータスイープ section 追加）
- `MAIN/CONTROL.csv`（VM: `ai_train_weekly_bad_hours="14,15,16"` に修正）

### 3-0E. 2026-04-25 追加済みロジック（セッション9: 監視・学習インフラ強化）

#### 監視強化
- **CONTROL変更ntfy通知**: `dashboard.py` に `_notify_control_change_ntfy()` を追加。`write_control_kv_csv_with_log()` からすべての CONTROL 書き込み後に fire-and-forget で ntfy へ差分通知を送る（Priority=low, Tag=gear）
- **週次ntfyレポート**: `tools/send_weekly_summary_ntfy.py` を新規作成。`ouroboros-weekly-autotrain.service` の `ExecStartPost` として自動実行。送信内容: 週間TP/SL/WR、AI閾値変化、Shadow判定、fast_MA近接率、LLM提案

#### 過去データ収集インフラ
- **`tools/fetch_historical_ohlc.py`** 新規作成: bitFlyer getexecutions API（公開API）から FX_BTC_JPY tick データを取得し 5分OHLC に集計
  - `--pages N --bar-min 5 --out data/historical_ohlc.csv`
  - `--resume` で `data/historical_ohlc.state.json` の `min_exec_id` から継続取得（古い約定IDへ遡る）
  - アトミック書き込み（`.csv.tmp` → rename）
  - レート制限: 0.5秒間隔

#### バックテスト反復学習エンジン
- **`tools/run_backtest.py`** 新規作成: `data/historical_ohlc.csv` を使い売買シミュレーションでAI学習サンプルを自動生成
  - エントリーシグナル: fast MA(5) × slow MA(20) クロス
  - `_compute_ai_score()`: base=0.60、trend/MA gap/volatility/ER/時間帯で±調整（JST換算）
  - TP/SL シミュレーション: 前方 `max_hold=36` 本ルックアヘッドで判定
  - 出力: `logs/backtest/ai_training_log_backtest.csv`（26列、`AI_TRAIN_FIELDS` 準拠）
  - ゲート: `ai_train_include_backtest=1` かつ min 300件 + PF ≥ 1.0 で学習に混合（boost=0.30x）
- **`/data` コマンド** (`commands/data.md`) 新規作成: OHLC状況・バックテストサンプル管理・日次ログ統計
- **`/backtest` コマンド** (`commands/backtest.md`) 新規作成: データfetch→バックテスト実行→ゲート確認→有効化の全工程

#### Shadow A/Bテスト（fast_MA距離）
- **`CONTROL_shadow.csv`**: `buy_fast_ma_distance_pct=0.06`（MAIN は 0.08）— 近接フィルターを緩めた場合のWR/約定率を計測
- **`CONTROL_shadow.csv`**: `sell_fast_ma_distance_pct=0.08`（旧 0.10）に変更

#### CONTROL変更
- `ai_train_weekly_bad_hours` を `""` → `"14,15,16"` に設定（14時WR=42%/15時=38%/16時=0% の学習ペナルティ weight=0.70 を適用）

#### 影響ファイル（このバッチ）
- `MAIN/dashboard.py`（v1.1.9: `_notify_control_change_ntfy()` 追加）
- `MAIN/tools/send_weekly_summary_ntfy.py`（新規）
- `MAIN/tools/fetch_historical_ohlc.py`（新規）
- `MAIN/tools/run_backtest.py`（新規）
- `MAIN/deploy/systemd/ouroboros-weekly-autotrain.service`（ExecStartPost 追加）
- `MAIN/CONTROL_shadow.csv`（buy_fast_ma_distance_pct=0.06, sell_fast_ma_distance_pct=0.08）
- `MAIN/CONTROL.csv`（ai_train_weekly_bad_hours="14,15,16"）
- `.claude/commands/backtest.md`（新規）
- `.claude/commands/data.md`（新規）
- `CLAUDE.md`（スキルマップ更新）

### 3-1. Drift Watch
- スクリプト: `MAIN/tools/market_drift_watch.py`
- serviceテンプレート: `MAIN/deploy/systemd/ouroboros-drift-watch.service`
- timerテンプレート: `MAIN/deploy/systemd/ouroboros-drift-watch.timer`
- timer: 30分ごと (`OnCalendar=*-*-* *:00,30:00`)

### 3-2. Weekly Auto Feedback
- スクリプト: `MAIN/tools/weekly_auto_feedback.py`
- serviceテンプレート: `MAIN/deploy/systemd/ouroboros-weekly-autotrain.service`
- timerテンプレート: `MAIN/deploy/systemd/ouroboros-weekly-autotrain.timer`
- timer: 毎週月曜 00:20 (`OnCalendar=Mon *-*-* 00:20:00`)

### 3-3. Trade Notifier
- スクリプト: `MAIN/tools/trade_event_notifier.py`
- timer: 60秒ごと (`OnUnitActiveSec=60s`)
- 状態変化通知対象に `runner/dashboard/ngrok/risk_stop/drift_state_changed` を含む。
- 終業レポート:
  - `runner_alive ON->OFF`
  - `SKIP_OUT_OF_TIME`
  - 日付跨ぎ時の未送信補完 (`day_rollover`)
  のいずれかで 1 日 1 回送信。
- 日次反省:
  - `daily_report_out/daily_reflection_YYYYMMDD.json` を保存
  - `勝因/敗因/翌日アクション/翌日推奨設定` を通知本文に含む
  - VM 上の Ollama (`http://127.0.0.1:11434`, `qwen2.5:1.5b`) を優先利用、失敗/低品質時は fallback
  - 2026-04-11 以降は `trade_notify_daily_reflection_llm_provider=openai` または `trade_notify_daily_reflection_llm_mode=openai` で OpenAI Responses API へ切替可能。APIキーは `OPENAI_API_KEY` など環境変数で渡し、secrets.toml へ直書きしない
  - `llm_mode=auto` かつ `provider=openai` で OpenAI が失敗した場合は Ollama -> deterministic fallback の順に落ちるため、通知処理自体は止めない
  - 現在は `daily reflection=1.5b / 240s / 650 chars` を推奨
- 自動承認:
  - 現在の安全運用は `ai_train_weekly_bad_hours,no_paper_hours` のみ allowlist
  - `min_confidence=high`, `max_changes=2`
  - `daily_loss_limit_pct` と `streak_stop_*` は手動承認のまま

### 3-4. Dashboard
- ファイル: `MAIN/dashboard.py`
- バージョン: `v1.1.9`
- タイトル: 英語固定 (`Trading Bot Dashboard`)
- UI追加済み機能:
  - Live Trading Desk（全タブ共通）
  - 約定テープ
  - セッション損益ラダー
  - リスク予算ゲージ
  - ドリフト復帰タイムライン
  - ワンクリック再現（負けトレード）

### 3-5. Widget Status
- スクリプト: `MAIN/tools/widget_status.py`
- サーバーバージョン: `OuroborosWidget/1.0`
- 起動ラッパー: `MAIN/tools/start_widget_status_server.sh`
- VM systemdテンプレート: `MAIN/deploy/systemd/ouroboros-widget-status.service`
- Mac常駐化:
  - install: `MAIN/tools/install_widget_status_launchagent.sh`
  - uninstall: `MAIN/tools/uninstall_widget_status_launchagent.sh`
- Ubuntu常駐化:
  - install: `MAIN/tools/install_systemd_services.sh --with-widget-status`
  - unit: `ouroboros-widget-status.service`
- エンドポイント:
  - `/` または `/widget` : コンパクトWeb表示
  - `/widget-status.json` : 機械取得
  - `/widget-status.txt` : CLI/通知向け簡易テキスト
- 2026-04-04 追加:
  - `shadow_day` を payload へ追加
  - 表示内容: 当日 shadow 損益 / 決済件数 / 勝率 / 最終結果
  - Scriptable `OuroborosWidget.local` / `OuroborosWidgetMoney` と Web/JSON/SwiftBar で参照可能
- 連携サンプル:
  - Mac: `MAIN/widget/swiftbar/ouroboros.1m.sh`
  - iPhone: `MAIN/widget/scriptable/OuroborosWidget.js`
  - 手順書: `MAIN/WIDGETS.md`

### 3-6. Morning Start Guard
- スクリプト: `MAIN/tools/morning_start_guard.py`
- serviceテンプレート: `MAIN/deploy/systemd/ouroboros-morning-start-check.service`
- timerテンプレート: `MAIN/deploy/systemd/ouroboros-morning-start-check.timer`
- timer: 15分ごと (`OnUnitActiveSec=15min`)
- 役割:
  - `start_hour` の20分前〜5分後だけ判定
  - `paper_mode=0 / live_enabled=1 / observe_only=0 / safety_hard_block=0`
  - `_risk_stop=OFF / _streak_stop=OFF / _drift_watch.status=NORMAL`
  - OKなら `today_on=1` と `trade_enabled=1` を戻す
  - `ouroboros-bot.service` が落ちていれば起動
  - 条件未達時は通知のみ
- 2026-03-29追加:
  - notifier が前日 `daily_loss_breach` で `trade_enabled=0` にした場合
  - かつ `drift=INSUFFICIENT` でも `trade_paused_by_drift=false`
  - なら朝だけ `sample_collection` モードで `trade_enabled=1` を戻してサンプル回収を許可する
- 2026-04-01追加:
  - `daily_loss_breach` 起点でなくても、`drift=INSUFFICIENT` の不足が軽い (`remaining_samples <= 4`) 場合は朝だけ `sample_collection` を許可
  - `0/6` のような深い不足でも、既定では `remaining_samples <= 6` なら `deep sample_collection` を許可
  - deep回復では同時に `daily_loss_limit_pct=-0.30` / `streak_stop_enabled=1` / `streak_stop_max_losses=2` を入れる
  - 退避値は `state._drift_watch.*_before_drift` へ保存し、後段の drift watch 復帰処理で戻せる形にする
  - `trade_enabled=0` を完全な手動停止にしたい日は `observe_only=1` か `safety_hard_block=1` を優先する

### 3-7. Shadow Runner
- serviceテンプレート: `MAIN/deploy/systemd/ouroboros-shadow.service`
- 実行:
  - `OUROBOROS_INSTANCE=shadow`
  - `OUROBOROS_CONTROL_PATH=MAIN/CONTROL_shadow.csv`
  - `OUROBOROS_RUN_LOCK_PATH=MAIN/.run_lock_shadow`
- state/log:
  - state: `MAIN/state_shadow.json`
  - log: `logs/instances/shadow/trade_log_YYYYMMDD.csv`
  - runner log: `MAIN/run_shadow.log`
- 2026-04-04 実機確認:
  - `ouroboros-shadow.service` は `active (running)`
  - `run_shadow.log` は 5 分ごとに tick 継続
  - `CONTROL_shadow.csv` は `paper_mode=1 / live_enabled=0 / trade_enabled=1 / start_hour=0 / end_hour=24`
  - shadow サンプルは `logs/instances/shadow/` 側に出るため、main の `logs/trade_log_*.csv` だけ見ても shadow 稼働は確認できない
  - `state_shadow.json` は main ほど情報を載せていないので、稼働確認は service / `run_shadow.log` / `logs/instances/shadow/` を優先する
  - `ouroboros-shadow.service` は long-running なので、`bot.py` / `run.py` を差し替えた日は `ouroboros-bot.service` だけでなく `ouroboros-shadow.service` も再起動すること
  - 実例: 2026-04-04 の `eod_entry_window` 修正は shadow service が 2026-03-11 起動のままで stale だったため、16:06 / 16:21 / 16:31 の post-cutoff `PAPER BUY` が残った。2026-04-04 16:36 JST に shadow service 再起動で解消方向
  - 2026-04-04 16:41 JST 以降は `16:41 / 16:46 / 16:51 / 16:56 / 17:01 / 17:06` に `OBSERVE_TIME_BLOCK | eod_entry_window cutoff=15:59:30` を確認。shadow でも EOD 直前/直後の新規 entry 抑止が live で効いた
- 学習への反映:
  - 現在は `ai_train_include_shadow=1`
  - `ai_train_shadow_boost=0.70`
  - つまり shadow サンプルは AI 再学習に重み付きで混ざる
- 2026-04-04 timeout傾向と対策:
  - closed 11件のうち `TIMEOUT 5 / EOD 4 / SL 1 / TP 1`
  - `TIMEOUT` は「全く伸びない玉」だけでなく、「少し利が乗ったのに TP に届かず戻された玉」も混在
  - そのため shadow だけ `exit_technical_enabled=1` を有効化し、紙上で reversal の早期 exit を先行検証する
  - さらに shadow だけ `trend_strength_filter_enabled=1` を有効化し、`trend_strength_lookback_n=20 / trend_strength_min_er=0.28` で弱いトレンドを `OBSERVE_TREND_STRENGTH_WEAK` へ逃がして choppy entry を先に減らす
  - 2026-04-05 の shadow は `trend_weak=4 / TIMEOUT=2 / TP=1`。弱い下降候補は弾けている一方、`best_fav<0.05%` の flat TIMEOUT が残ったため、shadow だけ `weak_progress_exit_enabled=1 / min_hold=30 / max_best_fav=0.05` を追加して dead trade を少し早く畳む
  - 2026-04-08 の shadow `SL 1本` は flat trade ではなく、`best_fav=0.119989%` を一度見せたあとに反転して `PAPER_EXIT_SL` になった
  - つまり 4/8 の残課題は `WEAK_PROGRESS` ではなく、**反転巻き込み型の負け**。`利確未遂` より `伸びた後の戻し` として扱う方が正しい
  - 2026-04-09 から widget / 終業レポートの `影日次` は `exit_tech` に加えて `trend_weak` / `weak` / `pto` / `timeout` を表示する
  - `weak` は `WEAK_PROGRESS` で早めに畳めた flat trade、`pto` は `best_fav>=0.08%` まで進んだあと technical timeout へ落ちた trade、`timeout` はそのどちらでもない純TIMEOUT を表す
  - 2026-04-09 以降は shadow だけ `progress_reversal_exit_enabled=1 / min_hold=20 / min_best_fav=0.08 / max_current_fav=0.03` も有効
  - `pr` は `PROGRESS_REVERSAL` で、`best_fav>=0.08%` を一度見せた玉が `current_fav<=0.03%` まで戻した時に technical timeout を待たずに逃がした件数を表す
  - 2026-04-11 以降は shadow だけ `no_follow_through_exit_enabled=1 / min_hold=5 / max_best_fav=0.01 / max_current_fav=0.00` も有効
  - `nf` は `NO_FOLLOW_THROUGH` で、HTF同方向でも初動でまったく伸びず `best_fav<=0.01%` かつ `current_fav<=0.00%` の玉を SL 前に早めに畳んだ件数を表す
  - 2026-04-09 以降は shadow だけ `htf15_context_enabled=1 / htf60_context_enabled=1 / htf_context_lookback_n=8 / htf_bias_slope_pct=0.02 / ai_use_htf_context=1` も有効
  - 5分足の既存判断に加えて、**15分足は `bias + trendline + channel`、60分足は `bias` だけ** を AI 判定へ足す。main は既定 OFF のまま
  - 2026-04-10 の `14:27 BUY` は `htf15=UP / htf60=DOWN` のねじれで `WEAK_PROGRESS` へ落ちたため、shadow だけ `htf60_countertrend_penalty=0.20 / htf15_60_conflict_penalty=0.25` を追加
  - これで「15分足が順でも 60分足が逆」の玉は、通常の HTF bias 点に加えてさらに score を下げる
  - 2026-04-10 以降は `OBSERVE_AI_BLOCK` note に `htf60_countertrend=1 / htf15_60_conflict=1` を埋め、日次通知と widget でも `HTF60逆風` / `15/60ねじれ` のブロック件数を追える
  - 2026-04-10 以降の終業反省は `shadow調整=filter / htf / exit` の3本立て。`shadow_htf_hint` は `HTF60逆風` と `15/60ねじれ` の件数変化を見て、維持 / 強め / 観察 を出す
  - 終業通知の `【要約】` は、shadow の `exit_tech` が前日より増えた日に `shadow注目=技術的exit N件 (前日比 +M)` を追記する
  - 日次反省の LLM prompt / fallback は `shadow_filter_hint / reason` に加えて `shadow_exit_hint / reason` も読むように更新済み。翌日の `維持 / 少し緩める / 少し強める` と `WEAK_PROGRESS の維持 / 少し早め / 観察` を本文へ書きやすくした
  - widget / daily-reflection page も最新の `shadow_filter_hint / shadow_exit_hint` を読む。large widget 下段と reflection detail に `shadow調整=filter... / exit...` が出る
  - 日次反省は `loss_pattern_breakdown` も持ち、`反転巻き込み / 伸び不足 / entry遅れ` の支配的な負け型を `【日次レビュー】` / `【反省】` / LLM prompt に出す
  - 日次反省は `opportunity_pattern_breakdown` も持ち、`entry約定失敗 / exit取り逃し / 時間帯回避 / 時間ブロック / spread回避` の支配的な機会損失を `【日次レビュー】` / `【反省】` / LLM prompt に出す
  - 週次 LLM も `shadow` を比較対象に含め、`_weekly_auto_feedback.shadow_weekly_review` へ `昇格候補 / 保留 / 差し戻し / 評価保留` を保存する
  - **2026-04-23**: `_check_and_update_shadow_inclusion()` を `weekly_auto_feedback.py` へ追加。週次 shadow レポートの WR/PF を自動評価し、`ai_train_include_shadow` を自動変更する
    - Promote (→1): Shadow WR ≥ 44% AND PF ≥ 1.0 AND closed_n ≥ 10
    - Exclude (→0): Shadow WR < 38% OR PF < 0.9
    - Hold: 中間値 — 変更なし
    - 結果は `state._weekly_auto_feedback.shadow_inclusion` に記録される
  - 週次 LLM はさらに `main` / `shadow` の負け型・機会損失の差分を見て、`pattern_hint` / `pattern_reason` へ「entry品質不足 / 執行品質不足 / 逃がし不足 / 伸び不足 / 昇格阻害小」などを残す
  - widget / Web の `今週累計` は `state.json` の `_weekly_auto_feedback.shadow_weekly_review` を読み、`保留 / entry品質不足` のような週次ヒントを detail 行へ出す
  - 週次の既定比較元は `../logs/instances/shadow`。必要なら `tools/weekly_auto_feedback.py --shadow-logs-dir ...` で差し替える
  - 2026-04-04 VM dry-run では `20260323-20260329` の shadow 週次比較が実行され、`decision=評価保留 / reason=main_closed=6, shadow_closed=140 でサンプル不足` を確認
  - 2026-04-08 に `MEAN_REVERSION_STRATEGY_SPEC.md` Phase 1 を `bot.py` へ差分追加済み
    - 追加 result: `OBSERVE_MR / OBSERVE_MR_FILTER_NG / OBSERVE_MR_TRIGGER`
    - ただし安全のため **`observe_only=1` かつ `mr_observe_enabled=1` の時だけ** 動く
    - 既定 OFF のため、現行 main / shadow の売買挙動は変わらない
    - note には `strategy=MR / mr_score / mr_rank / mr_level_type / mr_reclaim / mr_stop_pct / mr_htf15_bias / mr_htf15_trendline / mr_htf15_channel_pos / mr_htf60_bias` などを埋め込む
    - 次段階は「専用 observe で note 品質確認 -> A/B rank の分布確認 -> PAPER 化」

### 3-8. MR Observe Runner
- serviceテンプレート: `MAIN/deploy/systemd/ouroboros-mr-observe.service`
- フェーズ: `phase1-observe-only`
- 実行:
  - `OUROBOROS_INSTANCE=mr_observe`
  - `OUROBOROS_CONTROL_PATH=MAIN/CONTROL_mr_observe.csv`
  - `OUROBOROS_RUN_LOCK_PATH=MAIN/.run_lock_mr_observe`
- state/log:
  - state: `MAIN/state_mr_observe.json`
  - log: `logs/instances/mr_observe/trade_log_YYYYMMDD.csv`
  - runner log: `MAIN/run_mr_observe.log`
- 役割:
  - `observe_only=1`
  - `mr_observe_enabled=1`
  - 既存売買はせず、`OBSERVE_MR*` と note 品質だけを貯める専用 instance
- 見るポイント:
  - `OBSERVE_MR / OBSERVE_MR_FILTER_NG / OBSERVE_MR_TRIGGER` の件数
  - `mr_rank=A/B/C` 分布
  - `mr_level_type / mr_reclaim / mr_stop_pct / mr_htf15_bias / mr_htf15_trendline / mr_htf15_channel_pos / mr_htf60_bias` の偏り
  - ざっくり集計は `python3 tools/mr_observe_summary.py --day8 YYYYMMDD` で確認できる

## 4. 現在の重要デフォルト（テンプレート基準）

### 4-1. Drift Watch ExecStart（テンプレ）
`MAIN/deploy/systemd/ouroboros-drift-watch.service` は以下を含む:
- `--min-recent-closed 6`
- `--min-baseline-closed 25`
- `--pf-drop-th 0.15`
- `--avg-ret-drop-th 0.02`
- `--win-rate-drop-th 6`
- `--resume-require-consecutive-normal 4`
- `--resume-canary-runs 2`
- `--apply-train-freeze --auto-unfreeze`
- `--apply-trade-pause --auto-resume-trade`
- `--apply-hour-block --auto-unblock-hours`
- `--apply-risk-tighten --auto-restore-risk`
- `--risk-alert-daily-loss-limit-pct -0.30`
- `--risk-alert-streak-max-losses 2`
- `--insufficient-auto-relax-hours`
- `--insufficient-relax-after-runs 4`
- `--insufficient-relax-drop-hours 1`

### 4-2. Bot エントリー安全化デフォルト（2026-03-29追加）
- `buy_fast_ma_distance_pct=0.12`
  - BUY時に価格が fast MA に近すぎると `OBSERVE_BUY_FAST_MA_NEAR`
- `sell_fast_ma_distance_pct=0.10`
  - 既存の SELL 側 fast MA 近接見送り
- `trend_flip_cooldown_min=10`
  - `DOWN->UP` / `UP->DOWN` 直後10分は `OBSERVE_TREND_FLIP_COOLDOWN`
- `canary_tp_scale=0.65`
  - CANARY時だけ TP を 65% に縮めてサンプル回収を優先
- `news_entry_block_ahead_min=60`
  - 昼休み/ニュース帯が 60 分以内に迫っていたら `SKIP_NEWS (NEWS_AHEAD ...)`
- `pre_news_exit_buffer_min=10`
  - 既存ポジションは昼休み/ニュース帯の 10 分前から `PAPER_EXIT_PRENEWS` で逃がす
- `pre_news_exit_min_hold_min=5`
  - 建てた直後の即クローズを避けるため、最低 5 分保有する
- 2026-03-29 夜修正:
  - live exit の limit は `BUY=ask+offset / SELL=bid-offset` を使う
  - 理由: TP/SL 到達後でも、従来の「板の内側 limit」で exit unfilled が起きていたため
- 2026-04-02 追加:
  - 新規エントリーは昼休み/ニュース帯を跨ぐ見込みなら事前に見送る
  - 既存ポジションは昼休み/ニュース帯に入る前に `PAPER_EXIT_PRENEWS` で手仕舞いする
  - 理由: 2026-04-01 の SELL で、昼跨ぎ保有中に相場反転して SL になったため
- 2026-04-03 追加:
  - `buy_fast_ma_distance_pct` を `0.10 -> 0.12` へ引き上げ
  - 理由: 2026-04-02 15:26 の BUY は fast MA 距離 `0.1189%` でギリギリ通過後に即逆行したため
- `--insufficient-relax-max-applies 2`
- `--backup-dir backups/drift_watch`
- `--backup-max-keep 50`
- `--lock-file /tmp/ouroboros-drift-watch.lock`

### 4-3. Weekly AutoTrain ExecStart（テンプレ）
`MAIN/deploy/systemd/ouroboros-weekly-autotrain.service` は以下を含む:
- `--llm-mode auto`
- `--ollama-model qwen2.5:0.5b`
- `--ollama-timeout-sec 180`

## 5. 直近インシデントの確定事項（時系列）

### 5-1. 2026-03-12
- `weekly_auto_feedback.py` が古いままで `--llm-mode` 未対応 -> systemd起動失敗。
- 原因: 新版を `MAIN/` 直下へ置いたが、systemd実行先 `tools/` が旧版だった。
- 対応: `cp -f weekly_auto_feedback.py tools/weekly_auto_feedback.py` 後に再起動で解消。

### 5-2. 2026-03-12
- Ollama `qwen2.5:3b` / `1.5b` はメモリ不足で 500 または timeout。
- 対応:
  - swap 2GB追加
  - Ollama軽量化 (`OLLAMA_CONTEXT_LENGTH=512`, `OLLAMA_KEEP_ALIVE=30s`)
  - モデルを `qwen2.5:0.5b` に変更
  - timeoutを `180s` に延長
- 結果: `used=True`, `reason=ok` / `ok_with_fallback` を確認。

### 5-6. 2026-04-03
- 日次反省の既定 LLM を `qwen2.5:1.5b` へ引き上げ、timeout を `240s` へ延長。
- 理由: `0.5b` は安全だが、終業反省の文章が短くなりやすかった。
- 運用:
  - 日次反省: `1.5b / 240s / 650 chars`
  - 週次要約: 長いプロンプトでは `1.5b` が現行VMで timeout しやすいため `0.5b / 180s` を維持
  - 2026-04-11 以降は `tools/weekly_auto_feedback.py --llm-mode openai --openai-model gpt-5.4-mini` で週次だけ OpenAI Responses API に出せる
  - 両方とも 2026-04-03 時点で small-model 向けの判断ヒント付き prompt に調整済み
  - 失敗時は fallback 要約へ自動降格

### 5-7. 2026-04-04
- 2026-04-03 の終業レポートは `no_target/disabled` 時に `day_rollover` で再実行されやすかった。
- 対応:
  - `cursor.daily_goal_report_handled_day8` を追加
  - 通知先が無くても、その日分を「処理済み」として重複生成を止める
- 2026-04-04 04:41 JST 時点で VM 実機確認:
  - `cursor.daily_goal_report_handled_day8=20260403`
  - `cursor.daily_goal_report_sent_day8=""`
  - notifier は `sent=0 dry_run=False` で正常終了
  - 4/3 分の `day_rollover` 重複処理は live でも収束を確認
- 2026-04-03 16:39 の BUY は `end_hour=17` と `EOD_CUTOFF=15:59:30` の隙間で入っていた。
- 対応:
  - `resolve_eod_entry_block_status()` を追加
  - EOD window 中の新規 entry は `OBSERVE_TIME_BLOCK / eod_entry_window` で見送る
- shadow 実機確認:
  - `ouroboros-shadow.service` は `active (running)`
  - shadow ログは `logs/instances/shadow/trade_log_YYYYMMDD.csv`
  - `ai_train_include_shadow=1` / `ai_train_shadow_boost=0.70` で学習へ重み付き混合
- 2026-04-04 04:59 JST 時点で widget / 終業通知へ shadow 日次を追加:
  - live payload 例: `shadow_day=+5.054JPY / close=3 / win=66.7%`
  - iPhone 用は `OuroborosWidget.local.js` と `OuroborosWidgetMoney.js` へ反映済み
- 2026-04-04 04:41 JST 時点の live 状態:
  - `CANARY / trade ON / drift INSUFFICIENT`
  - `remaining_samples=3`
  - `daily_loss_limit_pct=-0.3`
  - `streak_stop_enabled=1 / streak_stop_max_losses=2`
  - 当日ログは取引時間前のため `SKIP_OUT_OF_TIME` のみ

### 5-3. 2026-03-12
- `market_drift_watch.py` と service引数ズレ (`--resume-require-consecutive-normal`) で起動失敗。
- 原因: serviceのみ先に更新、`tools/market_drift_watch.py` が旧版。
- 対応: `tools/` を最新版へ反映後、`install_systemd_services.sh --with-drift-watch` で再適用。

### 5-4. 2026-03-14
- Drift statusは `INSUFFICIENT`（`recent closed_n` が不足）。
- 挙動: 30分ごとのwatchは継続実行。`resume_ready` は `False` のまま。

### 5-5. 2026-03-18 / 2026-03-19
- 終業レポートが来ない日があった。
- 原因: 常駐 runner 運用では `runner_alive` が `OFF` にならず、従来の発火条件だけでは終業を検知できなかった。
- 対応:
  - `SKIP_OUT_OF_TIME` 到達時にも送信
  - 未送信のまま日付を跨いだら `day_rollover` で補完送信
  - notifier に日次反省 JSON 保存、LLM fallback、安全側 auto-apply を追加

## 6. 「時間が経つと元に戻る」理由（確定）
- 原因は `install_systemd_services.sh` 再実行時のテンプレート上書き。
- つまり「/etc/systemdだけ直接編集」「VM上で一時的にsed修正」は持続しない。
- 恒久化は必ず以下の順:
  1. `MAIN/deploy/systemd/*.service` を修正
  2. 必要なら `MAIN/tools/*.py` も修正
  3. `./tools/install_systemd_services.sh ...`
  4. `sudo systemctl daemon-reload`

## 7. 運用チェックコマンド（次トーク開始時）

```bash
cd ~/trading_bot/trading_bot/MAIN
pwd

# バージョン確認
python3 yt_tool.py --version
python3 - <<'PY'
import json
import pathlib
import re
import bot

root = pathlib.Path(".")
dashboard_text = (root / "dashboard.py").read_text(encoding="utf-8")
widget_text = (root / "tools/widget_status.py").read_text(encoding="utf-8")
handover = json.load(open(root / "HANDOVER.json", encoding="utf-8"))

dashboard = re.search(r'APP_VERSION = "([^"]+)"', dashboard_text).group(1)
widget = re.search(r'WIDGET_SERVER_VERSION = "([^"]+)"', widget_text).group(1)

print("bot.version=", bot.OUROBOROS_BOT_VERSION)
print("feature.schema=", bot.OUROBOROS_FEATURE_SCHEMA_VERSION)
print("dashboard.version=", dashboard)
print("widget.version=", widget)
print("mr_observe.phase=", "phase1-observe-only")
print("handover.updated_at_jst=", handover["meta"]["updated_at_jst"])
print("handover.versions=", handover["versions"])
PY

# サービス定義の実体確認（sudo必須）
sudo systemctl cat ouroboros-drift-watch.service | grep ExecStart
sudo systemctl cat ouroboros-weekly-autotrain.service | grep ExecStart
sudo systemctl cat ouroboros-trade-notifier.service | grep ExecStart
sudo systemctl cat ouroboros-widget-status.service | grep ExecStart
sudo systemctl cat ouroboros-morning-start-check.service | grep ExecStart
sudo systemctl cat ouroboros-shadow.service | grep ExecStart
sudo systemctl cat ouroboros-mr-observe.service | grep ExecStart

# タイマー確認
systemctl list-timers --all | grep ouroboros-drift-watch
systemctl list-timers --all | grep ouroboros-weekly-autotrain
systemctl list-timers --all | grep ouroboros-trade-notifier
systemctl list-timers --all | grep ouroboros-morning-start-check

# 直近ログ
sudo journalctl -u ouroboros-drift-watch.service -n 80 --no-pager
sudo journalctl -u ouroboros-weekly-autotrain.service -n 80 --no-pager
sudo journalctl -u ouroboros-trade-notifier.service -n 80 --no-pager
sudo journalctl -u ouroboros-widget-status.service -n 80 --no-pager
sudo journalctl -u ouroboros-morning-start-check.service -n 80 --no-pager

# state要点
python3 - <<'PY'
import json
s=json.load(open("state.json",encoding="utf-8"))
d=s.get("_drift_watch",{})
w=s.get("_weekly_auto_feedback",{}).get("llm_feedback",{})
print("drift.status=", d.get("status"))
print("drift.closed_n=", (d.get("recent_metrics") or {}).get("closed_n"))
print("drift.normal_streak=", d.get("normal_streak"))
print("drift.resume_ready=", d.get("resume_ready"))
print("weekly.llm.used=", w.get("used"))
print("weekly.llm.model=", w.get("model"))
print("weekly.llm.reason=", w.get("reason"))
print("weekly.llm.error=", w.get("error"))
PY

# CONTROL要点
grep -E '^(ai_auto_train_enabled|trade_enabled|no_paper_hours|daily_loss_limit_pct|streak_stop_enabled|streak_stop_max_losses),' CONTROL.csv
```

## 8. デプロイ標準手順（改修時）

### 8-1. ローカルで修正
- `tools/*.py`, `deploy/systemd/*.service|*.timer`, `dashboard.py` を編集。

### 8-2. VMへ反映（必要ファイルのみ）
- 原則は `tools/deploy_vm_components.sh` を使う。`scp` 手作業より版ズレ事故が少ない。
- 例:
```bash
VM_HOST=161.33.26.35
VM_KEY=/Users/tani/Downloads/ssh-key-2026-03-04-4.key
./tools/deploy_vm_components.sh --host "$VM_HOST" --key "$VM_KEY" --all-core
./tools/deploy_vm_components.sh --host "$VM_HOST" --key "$VM_KEY" --with-widget-status
./tools/deploy_vm_components.sh --host "$VM_HOST" --key "$VM_KEY" --with-morning-start-check
# VM上の MAIN パスが違う場合だけ --remote-main /actual/path/MAIN を追加
```

### 8-3. VMで反映確定
```bash
cd ~/trading_bot/trading_bot/MAIN
python3 -m py_compile tools/market_drift_watch.py tools/weekly_auto_feedback.py tools/widget_status.py
./tools/install_systemd_services.sh --with-drift-watch --with-weekly-autotrain --with-trade-notifier --with-widget-status --with-morning-start-check
sudo systemctl daemon-reload
sudo systemctl restart ouroboros-drift-watch.timer ouroboros-weekly-autotrain.timer ouroboros-trade-notifier.timer ouroboros-widget-status.service ouroboros-morning-start-check.timer
sudo systemctl start ouroboros-drift-watch.service
sudo systemctl start ouroboros-weekly-autotrain.service
sudo systemctl start ouroboros-morning-start-check.service
```

### 8-4. 反映確認
- `sudo systemctl cat ... | grep ExecStart`
- `sudo journalctl -u ... -n 80 --no-pager`
- state/CONTROL のキー確認。

## 9. よくある詰まりポイント
- `FileNotFoundError: state.json`
  - 原因: `cd` 先が違う。必ず MAIN 配下で実行。
- `systemctl: command not found`
  - 原因: Macで実行している。VMへSSHして実行。
- `channel ... connect failed: Connection refused`
  - 原因: SSHポートフォワード先で対象ポート未起動。
- `unrecognized arguments`
  - 原因: serviceの引数と `tools/*.py` の版ズレ。

## 10. 次トークへの引き継ぎテンプレ
- まず `MAIN/HANDOVER.md` と `MAIN/HANDOVER.json` を読む。
- 次に「7.運用チェックコマンド」を一括実行して現況を再取得。
- 取得結果をもとに、差分だけ改修する（テンプレート直編集を避ける）。

## 11. 今後の優先バックログ（高→低）

### 11-1. 未着手（既存）
1. notifierに「自動復帰発動（resume_ready/canary_ready成立）」専用イベントを追加。
2. `state_schema` 的な簡易検証スクリプトを追加（主要キー欠落検知）。
3. widget payload に日次損益要約を追加（`logs/` が存在する環境でのみ有効化）。
4. MR専用の observe インスタンスを切って、`OBSERVE_MR*` の note 品質と rank 分布を 1-3 日分ためる。
   - `observe_only=1`
   - `mr_observe_enabled=1`
   - 既存列・既存result・daily_report/audit を壊さない
   - 分布確認後に `rank=A` のみ PAPER 化を検討する

### 11-2. 次回候補（2026-04-23 提案）
5. **state_schema 検証の自動監査組み込み**: `audit.py` に主要キー欠落チェックを追加し、日次/週次タイマーで検出する（バックログ2と統合）
6. **audit.py の range モード改善**: `--start` より後に `--end` が来る場合に明示的なエラーメッセージを出す（現在はサイレントに 0 rows になる）
7. **dashboard ツールタブにシステムタイマー一覧を追加**: `systemctl list-timers` 相当の稼働/次回実行時刻を表示し、SSH なしで確認できるようにする（VM 専用機能）
8. **run_audit_today.sh のエラー通知**: audit で FATAL/ERROR が検出された場合に trade_event_notifier 経由でアラート送信
9. **backup corrupt アラートのクリア機能**: dashboard から `state_backup_corrupt` エントリを手動削除するボタン

### 11-3. 重要度低（将来検討）
10. **影付きコピー方式**: CONTROL.csv をシンボリックリンクで shadow/mr_observe と共有する設定値（`news_block_file` など）を一元管理する
