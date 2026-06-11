# Ouroboros Trading Spec Table

最終更新: 2026-06-12 JST（ATRベースTP/SLをgated実装＝Shadow先行検証開始。LIVE既定0で完全不変）  
実装バージョン: `bot.py=v2026.06.12.1`（**ATRベースTP/SL追加**: `atr_sl_multiplier`/`atr_tp_multiplier`[既定0=従来の固定TP/SLと完全同一]。SL=-(ATR%×倍率)を固定sl_pctよりワイドの時のみ採用[only-widen]・TPはR:R維持で連動。5年バックテスト[trading_knowledge/06 検証4]で固定SL-0.14%は5年-137%と一貫負け→ATR-SL×2.0で+134%・年次WF5/5通過。**CONTROL_shadow.csvのみ sl=2.0/tp=4.0 有効化＝Shadow先行検証・LIVEは未設定で不変**。検証後にLIVE適用を別途承認。chop再較正[chop_atr_low_pct=0.08 observe]継続）/ `ibkr_bot.py=v2026.06.11.4`（ATR-SL有効化済+トレンド整合observe／詳細は IBKR_AGENT_SPEC.md）/ `OUROBOROS_BOT_VERSION=2026.06.12.1` / インフラ安全性 2026-04-22 / 監視・学習インフラ 2026-04-25  
ツールバージョン（session31追加）: `state_schema_check.py`（新規: drift/weeklyスキーマバリデータ）/ `shadow_promotion_report.py`（Shadow SL reversal_wrap/profit_miss分類追加）  
ダッシュボードバージョン: Step1〜4+追加A〜E完了 / 2026-05-16 opsStatusCard compact化・Watchlist改善・IBKRサブエージェントパネル再設計  
特徴量スキーマ: `OUROBOROS_FEATURE_SCHEMA_VERSION=ohlc-chart-pattern-quality-market-phase-transition-near-tp-aiba-phase-fallback-mfe-mae-fib-elliott-v1`

この表は、`bot.py` に実装済みの売買・観測ロジックを一目で確認するための運用SPECです。  
既存の `result`、CSV列、pos_id、daily report/audit の契約は `SPEC_OUROBOROS_V1_MAIN.md` と `SPEC_OUROBOROS_TRADE_LOG_V1.md` を正とします。  
2026-05-13 以降は、実装側の単一起点として `ouroboros_contract.py` の `OUROBOROS_BOT_VERSION` / `OUROBOROS_FEATURE_SCHEMA_VERSION` / `TRADE_LOG_FIELDS` / `RESULT_ALLOWED` も正とします。
通知・ウィジェット監視の運用境界は `SPEC_OUROBOROS_NOTIFICATION_WIDGET_V1.md` と `MAIN/docs/notification_routes.md` を正とします。
2026-05-14 以降、通知レベルの共通化は `MAIN/tools/notification_policy.py` を単一起点として段階移行します。
2026-05-14 以降、widget のアプリ化は native 化ではなく `MAIN/tools/widget_status.py` の `/widget-app` PWA 導線を先行実装とし、Scriptable と `/widget-status.json` の後方互換を維持します。
2026-05-14 以降、`widget-app` は iPhone 向けに下部固定タブ風ナビと `Reflection Snapshot` を持ち、PWA オフライン時は最後の取得結果または簡易 offline 状態を返して白画面を避けます。
2026-05-14 以降、native shell は `MAIN/widget_native_ios/OuroborosWidgetNative/` に隔離し、既存 Web 経路を WKWebView で包む方式を正とします。

## 実装状況

| 領域 | 状態 | 主な設定キー | 主な note / state | 安全ゲート |
|---|---|---|---|---|
| 基本MA / trend | 実装済み | `fast_n`, `slow_n`, `buy_fast_ma_distance_pct`, `sell_fast_ma_distance_pct` | `ma_fast`, `ma_slow`, `trend`, `signal` | 既存のAI/時間/spread/risk gateを維持 |
| SMAクロス特徴 | 実装済み | `ma_cross_feature_enabled`, `ma_cross_recent_lookback_n`, `ma_cross_min_gap_pct`, `ma_cross_ai_boost`, `ma_cross_ai_penalty` | `ma_cross`, `ma_cross_recent`, `ma_cross_gap`, `ma_cross_aligned` | 単独発注禁止。AI scoreの軽い加点/減点のみ |
| RSI / BB / ATR / trend power | 実装済み | `tech_indicators_enabled`, `rsi_n`, `rsi_low`, `rsi_high`, `bb_n`, `bb_k`, `atr_n`, `trend_power_lookback_n` | `ti_rsi`, `ti_rsi_zone`, `ti_bb_zone`, `ti_atr_pct`, `technical_comp` | 単独発注禁止。過熱/逆行の補助評価 |
| 5分OHLC内部生成 | 実装済み | `chart_pattern_enabled`, `ohlc_timeframe_min`, `ohlc_max_bars` | `state._ohlc_current`, `state.ohlc_history`, `ticks` | ticker/ltpから内部生成。外部OHLC APIに依存しない |
| OHLC品質ゲート | 実装済み | `chart_pattern_min_bar_ticks`, `chart_pattern_quality_lookback_bars` | `cp_quality`, `cp_avg_ticks`, `pattern_quality` | `cp_quality=OK` の時だけチャートパターンをAI scoreへ反映 |
| チャートパターン | 実装済み | `swing_lookback`, `double_top_peak_tolerance_pct`, `double_bottom_trough_tolerance_pct`, `shoulder_tolerance_pct`, `head_min_excess_pct`, `neckline_break_confirm_bars` | `cp_name`, `cp_stage`, `cp_bias`, `cp_confirmed`, `cp_trend`, `cp_neckline`, `chart_pattern_comp` | `DOUBLE_TOP`, `DOUBLE_BOTTOM`, `HEAD_AND_SHOULDERS`。確定かつ品質OKのみ補助評価 |
| A/B/C局面 | 実装済み | `market_phase_enabled`, `market_phase_block_b_enabled`, `market_phase_lookback_n`, `market_phase_flat_slope_pct`, `market_phase_flat_gap_pct`, `market_phase_range_max_width_pct`, `market_phase_ai_boost`, `market_phase_ai_penalty`, `trade_notify_market_phase_enabled` | `phase`, `phase_reason`, `phase_slope`, `phase_gap`, `phase_range`, `up_break`, `down_break`, `phase_momentum`, `phase_transition`, `state._market_phase`, `market_phase_comp` | A=下落、B=横ばい、C=上昇。MA不明時はOHLCスイング/close変化で `SWING_*` / `OHLC_*_SOFT` に補完。B強制ブロックは既定OFFで、`market_phase_block_b_enabled=1` の時だけ `OBSERVE_PHASE_B` |
| 相場流 Phase 1 | 実装済み | `aiba_style_enabled`, `aiba_style_ai_enabled`, `aiba_ma_short_n`, `aiba_ma_mid_n`, `aiba_ma_long_n`, `aiba_nine_rule_alert_n`, `aiba_try_fail_lookback_n`, `aiba_try_fail_min_count` | `aiba_trend`, `aiba_cross`, `aiba_ppp`, `aiba_run`, `aiba_9`, `aiba_try_fail`, `aiba_style_comp` | くちばし/逆くちばし、PPP/逆PPP、9の法則警戒、トライ届かずを観測。AI反映は既定OFFで、`aiba_style_ai_enabled=1` の時だけ軽い補助点 |
| MFE/MAE/giveback検証 | 実装済み | open_pos内部追跡、`trade_event_notifier.py`, `trade_system_review.py`, `shadow_promotion_report.py` | exit note `best_fav`, `max_adv`, `current_fav`, review `avg_mfe_pct`, `avg_mae_proxy_pct`, `avg_giveback_pct`, `progress_reached_n` | 発注判断は変えず検証用ログを強化。過去ログは `max_adv` 欠損時に `mae_proxy=max(0,-ret_pct)` で近似 |
| MR observe / AランクPAPER | 実装済み | `observe_only=1`, `mr_observe_enabled=1`, `mr_*`, `mr_paper_enabled`, `mr_paper_min_rank`, `mr_paper_require_trigger`, `mr_paper_require_reclaim`, `htf15_context_enabled`, `htf60_context_enabled` | `strategy=MR`, `mr_score`, `mr_rank`, `mr_reclaim`, `mr_stop_pct`, `mr_paper=1` | `CONTROL_mr_observe.csv` 専用。既定OFFだがMR専用runnerではAランク + trigger + reclaimのみPAPER建玉化。`paper_mode=1 / live_enabled=0` を維持し、main発注へ直結しない |
| shadow先行検証 | 実装済み | `CONTROL_shadow.csv`, `exit_technical_enabled`, `trend_strength_filter_enabled`, `weak_progress_exit_enabled`, `progress_reversal_exit_enabled`, `near_tp_giveback_exit_enabled`, `no_follow_through_exit_enabled` | `weak`, `pr`, `ntp`, `pto`, `nf`, `trend_weak`, `HTF60逆風`, `15/60ねじれ` | shadowはpaper-only。main昇格前に3営業日以上を見る。`NEAR_TP_GIVEBACK` はTP寸前からの戻しを早逃げ検証する |
| MR observe専用runner | 実装済み | `CONTROL_mr_observe.csv`, `OUROBOROS_INSTANCE=mr_observe` | `logs/instances/mr_observe/`, `state_mr_observe.json` | main/shadowとは分離。AランクのみPAPER検証可、LIVE不可 |
| runner間隔 | 実装済み | systemd template | main `300s`, shadow `60s`, mr_observe `60s` | main負荷を維持し、観測系だけサンプル密度を上げる |
| 日次通知の特徴量表 | 実装済み | `trade_event_notifier.py` | `technical_feature_outcomes`, `pattern=...`, `pattern_quality=...` | 通知/反省用。発注判断そのものは変更しない |
| 日次反省VMスナップショットfallback | 実装済み | `trade_notify_daily_goal_snapshot_fallback_enabled`, `--daily-report-snapshot-dir` | `daily_review.report_log_source`, `daily_review.report_logs_dir`, `daily_review.report_log_source_reason`, `daily_review.report_snapshot_freshness` | Mac側の通常ログが空/薄い場合に `.local_llm/vm_snapshot/latest/logs` を日次反省の参照元へ使う。VM書込なし。timestamp付きsnapshotは `OK/STALE/UNKNOWN` で鮮度も出す |
| 総合トレードレビュー | 実装済み | `tools/trade_system_review.py`, VSCode task `harness: trade system review` | `review_out/trade_system_review_*.json`, `review_out/trade_system_review_*.md`, `feature_outcomes_top`, `effective_config` | ローカルのみ。CONTROL書込なし、外部APIなし、service restartなし。main/shadow/特徴量/不足情報を一括確認 |
| 実効設定ダンプ | 実装済み | `tools/effective_config_dump.py`, VSCode task `harness: effective config dump` | `watch_values`, `raw_control_high_risk`, `bot_version`, `feature_schema` | 朝チェック用。CONTROL/ai_modelをmergeした実効値を表示するだけで、CONTROL書込/VM再起動/外部APIなし |
| ローカルLLM助言 | 実装済み | `tools/run_local_llm_review.sh`, `.local_llm/` | local report JSON/MD | VM読み取り専用snapshot。VM書込/再起動なし |
| VM snapshot同期 | 実装済み | `tools/sync_vm_llm_inputs.sh` | `.local_llm/vm_snapshot/<timestamp>/`, `.local_llm/vm_snapshot/latest` | main/shadow/MRログ、`CONTROL.csv`, `ai_model.json`, `state.json`, `daily_reflection_*.json` を読み取り専用で取得。欠損時はエラー |
| LLM反省監査 | 実装済み | `tools/llm_reflection_audit.py`, VSCode task `harness: llm reflection audit` | `daily_reflection_*.json` の `llm_feedback` | 反省JSONの生成漏れ、LLM使用状況、エラー/警告を確認 |
| IB Gateway読み取り専用監視 | 実装済み（2026-05-06追加, 2026-05-08保守更新） | `test_ibkr_connection.py`, `tools/daily_ops_check.py`, `tools/ibkr_gateway_watch.py`, `tools/install_ibkr_gateway_watch_launchagent.sh` | `review_out/ibkr_connection_YYYYMMDD.json`, `review_out/daily_ops_check_YYYYMMDD.json`, `review_out/ibkr_gateway_watch_state.json`, `ibkr_watch_state` | TWS前面表示ではなくIB Gateway Paperを推奨。Socket Port 7497 / runtime / smoke鮮度 / watch最終実行を確認。注文は出さず、異常/復旧だけntfy通知。古い失敗ログは監査用に保持し、接続OK時は `active_error_available=false`。VM modeでは `effective_port_status=vm:127.0.0.1:7497` と `effective_runtime_status=VM IB Gateway` を優先し、watchは service active だけでなく VM内7497 listen も確認する |
| IBKR adapter責務分離 | 実装済み（2026-05-13追加） | `ibkr_adapter.py`, `ibkr_paper_adapter.py`, `ibkr_bot.py` | read-only経路は `IBKRAdapter`、paper order経路は `IBKRPaperAdapter` | `ibkr_adapter.py` は価格取得/口座取得などの読み取り専用層とし、注文系は `NotImplementedError`。paper order系だけ `ibkr_paper_adapter.py` に分離し、`ibkr_bot.py` からのみ使う |
| IB Gateway VM移行準備 | 実装済み（2026-05-06追加） | `tools/vm_ibkr_gateway_readiness.py`, `tools/open_vm_ibkr_tunnel.sh` | `review_out/vm_ibkr_gateway_readiness_YYYYMMDD.json/md`, `api_mode=vm_tunnel`, `vm_readiness`, `tunnel_status` | VMを読み取り専用で確認し、Java / headless GUI / IB Gateway配置 / 7497 listen を判定。7497は公開せずSSHトンネル `127.0.0.1:17497 -> VM:7497` でsmokeする。`daily_ops_check.py` と unified dashboard はVM readiness / 17497 tunnel / 17497 smoke成功をOK表示する。install/start/secret/orderはしない |
| VM dashboard/IBKR監視常駐 | 実装済み（2026-05-06追加） | `tools/deploy_vm_dashboard_ops.sh`, `deploy/systemd/ouroboros-unified-dashboard.service`, `deploy/systemd/ouroboros-ibkr-readonly-smoke.*`, `deploy/systemd/ouroboros-daily-ops-check.*`, `deploy/systemd/ouroboros-ibkr-gateway-watch.*` | VM `review_out/daily_ops_check_YYYYMMDD.json`, `review_out/ibkr_connection_YYYYMMDD.json`, `review_out/ibkr_gateway_watch_state.json` | Mac LaunchAgent依存を減らし、VM上で unified dashboard を `:8793` 配信、IBKR read-only smokeを15分ごと、Daily Ops/watchを5分ごとに更新。IBKRはVMローカル `127.0.0.1:7497` を直接使う。注文は出さない。Public 8793公開はOCI ingress/Tailscale等の別経路設定が必要 |
| IBKR SIGNAL_ONLY 銘柄スクリーニング | 実装済み（2026-05-04追加, 2026-05-08契約更新/日次化） | `signal_scanner_weekly.py`, `signal_scanner_outcome.py`, `deploy/systemd/ouroboros-signal-scanner-weekly.*`, `deploy/systemd/ouroboros-signal-scanner-daily.*`, `tools/unified_dashboard.html` | `review_out/signal_weekly_YYYYMMDD.json/csv/txt`, `review_out/signal_scanner_latest.json`, `review_out/signal_scanner_outcomes_latest.json`, `review_out/signal_scanner_feedback_latest.json`, ダッシュボード `🔍 シグナル候補` | 実注文禁止。FX/株を SIGNAL_ONLY で候補抽出し、`direction_candidate/current_price/spread/volatility/signal_reason/invalidation_price/target_price/risk_reward/max_loss_estimate/confidence/note` を保存。候補ありは `OBSERVE_OK`、候補なしは `OBSERVE_NO_SIGNAL`。月〜金 09:05 JST の daily timer で候補更新、週次 timer で通知付きレポート。`signal_scanner_outcome.py` は symbol別/side別/FX優先度を集計し、次回 scanner の confidence に最大 ±15 点で反映する。`FX/STOCK` の市場優先は各 closed サンプルが最低5件そろった時のみ有効。ダッシュボードでは `final confidence / base confidence / feedback補正 / feedback理由` と、要約欄の `fx_priority / min_closed_required / closed件数 / market補正` を同時表示 |
| VM Tailscale dashboard経路 | 実装済み（2026-05-07追加） | VM `tailscaled`, `ouroboros-unified-dashboard.service` | VM Tailscale IP `100.66.216.5`, iPhone URL `http://100.66.216.5:8793/tools/unified_dashboard.html` | VMをTailnetへ参加させ、iPhoneからTailscale経由で unified dashboard を閲覧する。VM内では `100.66.216.5:8793` が200 OK。Mac側Tailscaleが未接続ならMacからは疎通しないため、iPhone側TailscaleをONにして使う |
| VM KEIBA常駐 | 実装済み（2026-05-07追加） | `KEIBA/`, `deploy/systemd/ouroboros-keiba-streamlit.service`, `deploy/systemd/ouroboros-keiba-status-server.service`, `KEIBA/keiba_status_server.py`, `tools/unified_dashboard.html` | KEIBA app `http://100.66.216.5:8511`, KEIBA status `http://100.66.216.5:8789/keiba-status.json` | KEIBAをVMへ同期し、Streamlitを `0.0.0.0:8511`、status APIを `0.0.0.0:8789` でsystemd常駐。status APIのPOST操作は `KEIBA_ACTIONS_DISABLED=1` で無効化し、閲覧中心。unified dashboardはVM Tailscale上ではKEIBA URLを自動補正する |
| stale成果物レビュー | 実装済み（2026-05-13追加） | `tools/stale_artifact_review.py`, `review_out/stale_artifact_review_latest.json` | `stale_artifact_review_YYYYMMDD.json/md`, `stale_artifact_review_latest.json` | `stock_shadow_state.json`, `signal_scanner_latest.json`, `ibkr_vm_sync_status.json`, 旧 `trade_system_review_*` を非破壊で棚卸しする。削除や移動はせず、`STALE / FRESH / ARCHIVE_CANDIDATE` を先に可視化して、dashboard上で現役と誤認しにくくする |
| stale成果物archive plan | 実装済み（2026-05-13追加） | `tools/archive_stale_artifacts.py` | `archive_stale_artifacts_plan_YYYYMMDD.json`, `archive_stale_artifacts_plan_latest.json` | 既定は dry-run。`stale_artifact_review_latest.json` の `archive_candidates` を読み、まず移動 plan だけ作る。`--apply` を付けた時だけ `review_out/archive/legacy_review_*` へ移動する |
| IBKR live切り替え | 実装済み（2026-05-15完了） | `IBKR_CONTROL.csv: ibkr_port=7496`, `ouroboros-ibkr-bot.service` | `ibkr_state.json`, `review_out/ibkr_connection_latest.json`, trade_log `LIVE_*` ラベル | `ibkr_port` を 7497（paper）→ 7496（live）に変更。VM上の IB Gateway Live に接続し実注文が走る状態。trade_log の `LIVE_EXIT_TIMEOUT` で live 稼働確認済み |
| ibkr_bot ATR適応型TP | 実装済み（2026-05-15, v2026.05.15.4） | `ibkr_atr_tp_multiplier=1.5`（IBKR_CONTROL.csv） | ATR計算はbar データから取得、`tp_pct = max(base_tp, atr_multiplier × ATR/price × 100)` | ATR×1.5がbase TPを超える時だけTPを拡張。ボラティリティ低い日は通常TP維持 |
| ibkr_bot SLクールダウン | 実装済み（2026-05-15, v2026.05.15.4） | `ibkr_sl_cooldown_min=30`（IBKR_CONTROL.csv） | `state["sl_cooldown_until"]` に ET時刻文字列を保存 | SL後30分間はエントリーブロック。次回ループで自動解除（stateキーを削除） |
| ibkr_bot EODクローズ修正 | 実装済み（2026-05-15, v2026.05.15.4） | `ibkr_eod_close_hour_et`, `ibkr_eod_close_min_et` | `_is_eod_close_time()` | 旧: `hour == eod_h` のみ判定 → 再起動後に 16時以降でもクローズしないバグ。修正: `or now.hour > eod_h` を追加。即デプロイ後 `LIVE_EXIT_TIMEOUT` 発火確認済み |
| 動的ポート読み取り | 実装済み（2026-05-15） | `test_ibkr_connection.py`, `tools/daily_ops_check.py` | `_read_ibkr_port_from_control()` / `_read_ibkr_port()` | 両スクリプトが `IBKR_CONTROL.csv` の `ibkr_port` を実行時に読み取る。live移行前は 7497 ハードコードでダッシュボードに古いエラーが表示されていた問題を解消 |
| unified_dashboard Step1改善 | 実装済み（2026-05-15） | `tools/unified_dashboard.html` | `ibkrState` fetch from `/ibkr_state.json`, dynamic port in health tab | No.1: healthタブのIBKRポート表記を動的化（7496/7497自動判定）/ No.2: overviewにIBKRサマリーカード追加（モード/日次P&L/取引数/建玉）/ No.3: stocksタブにPaper API停止時の警告バナー追加 |
| unified_dashboard Step2改善 | 実装済み（2026-05-16） | `tools/unified_dashboard.html` | `renderIbkr()`, `_staleInfo()`, `_staleBadge()`, SECTIONS追加 | No.6: LLM評価が3日超staleで黄色バナー+バッジ表示 / No.10: 「IBKR 米株📈」タブを新設（ステータス+ops+サブエージェントを1箇所に集約。stocksタブは発注UI特化に整理）/ No.14: タブリネーム（ヘルス→監査・点検、シグナル候補→スキャン結果、シグナル精度→勝率分析、週次比較→週次レポート） |
| unified_dashboard 追加改善A・C・E | 実装済み（2026-05-16） | `tools/unified_dashboard.html` | `renderIbkr()` 拡張, `updateTopbar()` 変更 | A: IBKRタブ末尾に緊急停止コマンドカード（コピーボタン付き）/ C: VIX・選択銘柄・SLクールダウンをIBKRステータスカードに追加 / E: topbar時刻を「更新 X分前」形式に変更 |
| unified_dashboard Step3+追加改善B | 実装済み（2026-05-16） | `tools/unified_dashboard.html` | `_getTabBadge()`, `.nav-badge-dot`, SECTIONS再編, `_marketTimer=300000` | No.5: タブを5グループ化（ホーム/取引システム/シグナル分析/市場情報/システム）/ No.9: CoinGecko marketリフレッシュ60s→5分 / No.4: 未使用`isVmTailscaleHost()`削除 / No.15: newsをグループ末尾へ / 追加B: タブバッジ（IBKR赤/黄・BTC停止赤・監査警告黄）。残りはNo.8(CSSクラス化) のみ |
| IBKR import監査 | 実装済み（2026-05-13追加） | `tools/ibkr_import_audit.py`, `ibkr_adapter.py`, `ibkr_paper_adapter.py` | `paper_order_allowed_importers`, `paper_order_importers_actual`, `paper_order_importers_unexpected` | `ibkr_paper_adapter.py` を import してよい呼び出し元を `ibkr_bot.py` に限定して監査する。read-only utilities が誤って order-capable adapter を参照しないよう機械チェックする |
| shadow昇格レポート | 部分実装 | `tools/shadow_promotion_report.py` | `decision=OK/WAIT/NG`, `main/shadow/delta`, `mrA/B/C`, `feature_gate_review` | 全体PF/win/SL/closed/MR件数は判定済み。`phase` / `aiba_*` / `near_tp` は `REPORT_ONLY` で可視化済み。main昇格判定への自動反映はまだしない |
| インフラ安全性 | 実装済み（2026-04-22追加） | *(CONTROL設定: `daily_loss_limit_pct`, `ai_train_weekly_bad_hours`)* | `state.json` アトミック書き込み（.tmp→rename）/ 起動時孤児注文キャンセル（`state._orphan_cancel_history`）/ API リトライ（429/5xx 最大3回 バックオフ 1s→2s→4s）| POSIX `rename(2)` 保証。孤児注文は `state._open_pos` 未追跡の ACTIVE 注文のみ対象。API 4xx（429除く）は即例外でリトライなし |
| CONTROL変更ntfy通知 | 実装済み（2026-04-25追加） | `dashboard.py: _notify_control_change_ntfy()` | fire-and-forget。`write_control_kv_csv_with_log()` 呼び出し後に差分（最大5フィールド）を ntfy へ送信 | Priority=low, Tag=gear。ntfy_topic_url 未設定時はスキップ |
| 週次ntfyレポート | 実装済み（2026-04-25追加） | `tools/send_weekly_summary_ntfy.py` / `ouroboros-weekly-autotrain.service ExecStartPost` | 週間TP/SL/WR、AI閾値変化、Shadow判定、fast_MA近接率、LLM提案 | 毎週月曜 00:20 に weekly-autotrain 完了後に自動送信 |
| 過去OHLCデータ収集 | 実装済み（2026-04-25追加） | `tools/fetch_historical_ohlc.py` | `data/historical_ohlc.csv`（5分OHLC）/ `data/historical_ohlc.state.json`（resume状態） | bitFlyer getexecutions 公開API。`--resume` で継続取得可能 |
| バックテスト反復学習 | 実装済み（2026-04-25追加） | `tools/run_backtest.py` | `logs/backtest/ai_training_log_backtest.csv`（26列 AI_TRAIN_FIELDS 準拠） | ゲート: min 300件 + PF ≥ 1.0。`ai_train_include_backtest=1` で学習に boost=0.30x で混合 |
| Shadow A/Bテスト | 実行中（2026-04-25開始） | `CONTROL_shadow.csv: buy_fast_ma_distance_pct=0.06`（MAIN=0.08） | shadow WR/PF/fill_rate vs MAIN で fast_MA フィルター影響を計測 | `sell_fast_ma_distance_pct=0.08`（旧 0.10）も同時変更 |
| TP Trail（TP後トレーリング出口）| 実装済み（2026-05-21, v2026.05.21.1）| `bot.py` TP判定直後 / `CONTROL.csv: tp_trail_enabled=0, tp_trail_giveback_pct=0.08, tp_trail_max_min=20` | BitradeX高頻度スキャルピング分析より移植。TP到達後即出口→ピーク比0.08%戻し or 20分経過で出口に変更 | `tp_trail_enabled=0`（現在無効）。有効化前に2週間の動向確認推奨。高ボラ日（ATRパーセンタイル>75%）のみ試験運用を想定。`/regime` でQ1/Q2の時に有効化を検討 |
| BTC エントリーハードゲート3種追加（2026-05-16） | 実装済み（2026-05-16, v2026.05.16.1） | `bot.py` AI gate直後 / `CONTROL.csv: ai_threshold=0.80` | (A) CP_COUNTER_BLOCK: DoubleTop/Bottom確認済み×逆方向エントリー禁止 (B) TECH_COMP_BLOCK: technical_comp<-0.10でブロック (C) TRY_FAIL_BLOCK: aiba_try_fail_count≥3でブロック | 5/15-16損失分析。AIスコア高でも他シグナルが全逆の時にエントリーを止める。ai_threshold 0.73→0.80に同時引き上げ |
| BTC週次critic適用（2026-05-16週） | 適用済み（2026-05-16） | `CONTROL.csv`, `tools/weekly_btc_critic.py` | スコア33点/100点。auto-apply 2件 | `buy_fast_ma_distance_pct`: 0.06→0.04 / `sell_fast_ma_distance_pct`: 0.08→0.06。週94件のfast_ma_nearブロックが主因。来週`trend_strength_min_er`の引き下げ（0.30→0.25）を要検討 |
| IBKR週次critic適用（2026-05-04週） | 適用済み（2026-05-16） | `IBKR_CONTROL.csv`, `tools/weekly_ibkr_critic.py` | スコア65点/100点。エントリー週1件のみ | `ibkr_sma_min_divergence_pct`: 0.03→0.0（低ボラ相場で全件ブロックの主犯）/ `ibkr_setup_vwap_enabled`: 1→0（二重ブロック解除）/ `ibkr_max_trades_per_day`: 3→6 |
| IBKR多銘柄スキャン・多ポジション同時保有 | 実装済み（2026-05-16, v2026.05.16.1） | `ibkr_bot.py`, `IBKR_CONTROL.csv: ibkr_max_concurrent_positions=2` | `state["open_positions"]`（Dict[symbol, pos]）/ `_get_symbols()` / レガシー `open_pos` 後方互換維持 | 単一銘柄（QQQ固定）→ `ibkr_monitor_symbols` の6銘柄（AAPL,MSFT,NVDA,TSLA,QQQ,SPY）を毎ループスキャン。最大2ポジション同時保有。VIX/SLクールダウンは全銘柄共通。既存 `open_pos` → `open_positions` dict に自動マイグレーション |
| Dashboard opsStatusCard簡略化 | 実装済み（2026-05-16） | `tools/unified_dashboard.html`, `opsStatusCard()` | compact=true: 6項目pill表示（BTC Bot/IBKR API/Dashboard/IB Gateway/7日稼働率/GW Watch）/ compact=false: 12行→9行（VM Tunnel・VNC・clientId診断行を削除）| 警告バナー: 接続済み時は非表示。`ibkr?.connected`を優先チェックし、smoke_neededでも接続中なら"接続OK"表示 |
| Dashboard Watchlist改善 | 実装済み（2026-05-16） | `tools/unified_dashboard.html`, `renderOverview()` watchlist section | ↺リフレッシュボタン追加 / 未取得時はスケルトン表示（"---"）/ フッター3状態（更新X分前/取得中/取得エラー+再試行ボタン）| 価格テキストを24h変化率に連動して色付け（正=green/負=red/選択中=accent） |
| Dashboard IBKRサブエージェントパネル再設計 | 実装済み（2026-05-16） | `tools/unified_dashboard.html`, `_renderIbkrSubagentPanel()` | エージェントテーブル5列→3列（スケジュール・役割列を削除、ロールをサブタイトルへ）/ staleバナー1行化 / Gateway Watch・VM Syncカードをheader+pill形式にコンパクト化 / プリブリーフ・レビューはLLMテキストなし時にコンパクトノート表示 | ログsummary内の折り畳みに最終行プレビューを追加（展開なしで内容確認可） |

## 調査指示との照合

| 確認項目 | 現状 | 根拠 | 残り |
|---|---|---|---|
| ログ同期・実績定義の固定 | 実装済み | `sync_vm_llm_inputs.sh` が main/shadow/MR/CONTROL/state を取得し、欠損時に失敗する | 「サンプル」「実践」の呼び名は比較対象A/B/C指定後に最終固定 |
| 比較レポート標準化 | 実装済み | `trade_system_review.py` が main/shadow/特徴量/実効設定を同一形式で出力 | 比較対象A/B/Cが未指定のため差分比較は軸だけ |
| 特徴量別の損益分解 | 実装済み | `technical_feature_outcomes`, `market_phase_outcomes`, `feature_outcomes_top`, `avg_mfe_pct`, `avg_mae_proxy_pct`, `avg_giveback_pct` | 今後ログは `max_adv` で逆行も追跡。過去ログはproxy混在 |
| 実効設定ダンプ | 実装済み | `tools/effective_config_dump.py` と `trade_system_review.py` の `effective_config` | 朝チェックでCONTROL/ai_modelの実効値を確認する |
| shadow昇格ゲート強化 | 部分実装 | `shadow_promotion_report.py` がPF/win/SL/closed/MRで `OK/WAIT/NG`、特徴量別は `REPORT_ONLY` | `phase` / `aiba_*` / `near_tp` をmain昇格判定へ混ぜるのは、3営業日サンプル確認後 |
| ファイル整理計画 | 部分実装 | `.gitignore` や docs は追加済み | bak/legacyの削除・renameは未承認なので未実施 |
| UI/Widget診断表示 | 実装済み | widget/statusにversion/schema/goal/balance/shadow/reflection表示 | 実機スクショ確認は手動 |
| 日次反省のVM実ログ参照 | 実装済み | `report_log_source=vm_snapshot` で参照元を明示 | `report_snapshot_freshness=OK/STALE/UNKNOWN` で古いsnapshotを見分ける |

## 未実施・保留

| 項目 | 理由 | 次にやるなら |
|---|---|---|
| 比較対象システムA/B/Cの差分表 | A/B/Cが未指定 | main / shadow / MR / backtest のどれをA/B/Cにするか決めてから生成 |
| `phase` / `aiba_*` / `near_tp` 別shadow昇格ゲート | まだサンプル薄め。main昇格に直結するので慎重運用 | `feature_gate_review.status=REPORT_ONLY` のまま3営業日見てからゲート化 |
| 実OHLCベースの完全MAE | ticker間の最高/最安は現在はopen_pos追跡中心 | `max_adv` が今後蓄積された後に、過去proxyと分けて評価 |
| bak/legacy整理 | delete/rename禁止範囲 | archive方針をdocs化し、明示承認後に移動 |

## 使い方

### バージョン確認

```bash
cd ~/trading_bot/trading_bot/MAIN
python3 - <<'PY'
import bot
print("bot.version =", bot.OUROBOROS_BOT_VERSION)
print("feature.schema =", bot.OUROBOROS_FEATURE_SCHEMA_VERSION)
PY
```

### OHLC品質と観測runnerの確認

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

### 総合トレードレビュー

```bash
python3 tools/trade_system_review.py
python3 tools/trade_system_review.py --write
python3 tools/trade_system_review.py --snapshot-dir .local_llm/vm_snapshot/latest --write
```

出力先:
- `review_out/trade_system_review_YYYYMMDD_HHMMSS.json`
- `review_out/trade_system_review_YYYYMMDD_HHMMSS.md`

補足:
- `--snapshot-dir` は `tools/sync_vm_llm_inputs.sh` が作る読み取り専用snapshotを解析する
- snapshot解析でもCONTROL書込、VM service restart、外部API送信は行わない
- `feature_outcomes_top` は決済済み成績、`feature_presence_top` は成績化前のnote出現数を見る
- `avg_mfe_pct` は平均最大順行、`avg_mae_proxy_pct` は平均最大逆行または欠損時proxy、`avg_giveback_pct` は最大順行から終了時点までの戻し幅を見る

### 実効設定ダンプ

```bash
python3 tools/effective_config_dump.py
python3 tools/effective_config_dump.py --snapshot-dir .local_llm/vm_snapshot/latest
python3 tools/effective_config_dump.py --print-json
```

補足:
- CONTROLとai_modelをmergeした実効値を表示する
- CONTROL書込、VM service restart、外部API送信、secret読取は行わない
- VS Codeでは `harness: effective config dump` / `harness: effective config dump vm snapshot` から実行できる

### VMのrunner間隔確認

```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 \
  'systemctl show -p ExecStart --value ouroboros-bot.service; systemctl show -p ExecStart --value ouroboros-shadow.service; systemctl show -p ExecStart --value ouroboros-mr-observe.service'
```

## noteキーの読み方

| noteキー | 意味 |
|---|---|
| `cp_quality=OK` | 直近OHLCのtick密度が足りており、チャートパターン補助評価に使える |
| `cp_quality=THIN` | 足は生成されたがtickが薄い。ログには残すがAI scoreへ反映しない |
| `cp_name=DOUBLE_TOP` | ダブルトップ候補/確定 |
| `cp_name=DOUBLE_BOTTOM` | ダブルボトム候補/確定 |
| `cp_name=HEAD_AND_SHOULDERS` | ヘッドアンドショルダー候補/確定 |
| `cp_stage=CONFIRMED` | ネックライン突破などの確定条件を満たした |
| `cp_bias=BUY/SELL` | パターンが示す方向 |
| `chart_pattern_comp` | AI scoreへ入ったチャートパターン成分。品質OKかつ方向一致/逆行時のみ出る |
| `technical_comp` | RSI/BB/ATR/trend power由来のAI score成分 |
| `phase=A/B/C` | A=下落、B=横ばい、C=上昇の局面判定 |
| `phase_reason=MA_FLAT/MA_UP/MA_DOWN/SWING_UP/SWING_DOWN/OHLC_UP_SOFT/OHLC_DOWN_SOFT/OHLC_FLAT` | 局面判定の主理由 |
| `up_break=1` | 直前OHLC足の高値を上抜けた |
| `down_break=1` | 直前OHLC足の安値を下抜けた |
| `phase_momentum=UP_BREAK/DOWN_BREAK` | 局面方向と高値/安値ブレイクが一致した |
| `phase_transition=A->B/B->C/...` | A/B/C局面が前回から変わった時だけ出る転換タグ |
| `state._market_phase` | 現在局面、直近転換、転換時刻、理由、勢いを保持する |
| `market_phase_comp` | A/B/C局面由来のAI score成分。B局面や逆方向局面は減点 |
| `aiba_trend=UP/DOWN/NEUTRAL` | 相場式MA順序と傾きから見た環境 |
| `aiba_cross=KUCHIBASHI/REV_KUCHIBASHI` | 5MA/20MAのくちばし・逆くちばし |
| `aiba_ppp=PPP/REV_PPP` | 短期・中期・長期MAのパンパカパン/逆パンパカパン |
| `aiba_9=1` | 同方向MA順序の継続が警戒本数に達した。単独exitは禁止 |
| `aiba_try_fail=1` | 直近OHLCで高値未更新 + 終値下落が連続。BUY逆風、SELL補強候補 |
| `aiba_style_comp` | `aiba_style_ai_enabled=1` の時だけAI scoreへ入る相場流補助成分 |
| `exit_tech=NEAR_TP_GIVEBACK` | TPの一定割合まで近づいた後、含み益を戻した玉をshadowで早逃げした |

## 日次レビュー追加

| 項目 | 意味 |
|---|---|
| `market_phase_outcomes.A/B/C` | 局面別の約定数、勝率、損益、TP/SL/TIMEOUT、break件数 |
| `market_phase_transition_counts` | `A->B` / `B->C` などの局面転換回数 |
| `observe_phase_b_n` | `OBSERVE_PHASE_B` でB局面を回避した件数 |
| `daily_review.report_log_source` | 日次反省が `primary` / `vm_snapshot` のどちらを参照したか |
| `daily_review.report_logs_dir` | 日次反省が実際に読んだログディレクトリ |
| 通知本文 `局面=... / 転換=...` | `A:2件 win50% pnl+10 br1 / 転換=B->C:1 / 最新=B->C` のように表示 |

## 変更時ルール

- 売買ロジック、noteキー、stateキー、systemd間隔を変えたら、このファイルと `HANDOVER.json` / `HANDOVER.md` / `COMMANDS_QUICK.md` を同時更新する。
- 新しい予測ロジックは、原則 `observe-only` または `shadow-paper` から始める。
- `cp_quality=THIN` のデータで昇格判断しない。
- `result` 名やCSV列の削除・改名は禁止。必要なら root のSPECも同時更新する。
