# ダッシュボード改善計画

最終更新: 2026-05-16 JST（Chart AI統合・モバイル最適化F完了）  
対象ファイル: `tools/unified_dashboard.html`（5,667行 / 298KB）  
配信URL: `http://100.66.216.5:8793/tools/unified_dashboard.html`  
デプロイ: `scp ... ubuntu@161.33.26.35:/home/ubuntu/trading_bot/MAIN/tools/unified_dashboard.html`

---

## 保守点検サマリー（2026-05-15実施）

### 構成概要

```
unified_dashboard.html
├── CSS: 311行 (埋め込み)
├── JS: ~4,800行 (埋め込み)
└── HTML: ~350行 (テンプレート部)

データソース (14種)              内部サービス (4種)
├── review_out/*.json            ├── :8787 Widget (BTC bot)  ✓
├── ibkr_connection_latest.json  ├── :8789 KEIBA             ✓
├── signal_scanner_*.json        ├── :8793 静的サーバ         ✓
├── stock_shadow_state.json      └── :8812 Paper Trading API ✗ 停止中
└── .local_llm/ibkr/prebrief/
```

### 14タブ構成

| # | タブID | 表示名 | グループ | 主要データ |
|---|--------|--------|----------|-----------|
| 1 | overview | 概要◈ | メイン | widget, ops, keiba |
| 2 | ouroboros | Ouroboros BTC₿ | メイン | widget-status.json |
| 3 | keiba | KEIBA競馬🐎 | メイン | keiba-status.json |
| 4 | charts | チャート📊 | メイン | CoinGecko OHLC |
| 5 | portfolio | ポートフォリオ💼 | メイン | CoinGecko + localStorage |
| 6 | stocks | 株式▣ | メイン | :8812 Paper API（停止中） |
| 7 | scanner | シグナル候補🔍 | メイン | signal_scanner_latest.json |
| 8 | outcome | シグナル精度🎯 | メイン | signal_scanner_outcomes_latest.json |
| 9 | weekly-compare | 週次比較📅 | メイン | signal_weekly_history.json |
| 10 | market | マーケット📡 | メイン | CoinGecko + Frankfurter |
| 11 | news | ニュース📰 | メイン | RSS2JSON |
| 12 | health | ヘルス♥ | システム | daily_ops_check.json |
| 13 | agents | エージェント🤖 | システム | ibkr prebrief/review (LLM) |
| 14 | alerts | アラート🔔 | システム | localStorage |

---

## 改善項目一覧（優先度順）

### ✅ Step 1 — 完了（2026-05-15）

| No | 分類 | 問題 | 対応 | 状態 |
|----|------|------|------|------|
| 1 | バグ修正 | healthタブでIBKR接続エラー文が「7497が待ち受けていません」と誤表示 | healthタブのVM Readiness行とwarningバナーのポート表記を動的化（IBKR_CONTROLの `ibkr_port` を参照） | ✅ デプロイ済み |
| 2 | UI改善 | overviewにIBKR今日のP&L・建玉がない | overviewにIBKRサマリーカード追加（`/ibkr_state.json` から取得：モード/日次P&L/取引数/建玉） | ✅ デプロイ済み |
| 3 | UI改善 | stocksタブ：Paper APIが停止中なのに発注UIが表示される | Paper API停止時は「準備中」警告バナーをtopに表示。liveモード時はbot稼働中の説明を添える | ✅ デプロイ済み |

### ✅ Step 2 — 完了（2026-05-16）

| No | 分類 | 問題 | 対応 | 状態 |
|----|------|------|------|------|
| 6 | 表示改善 | agentsタブのLLM評価が1週間staleで気づきにくい | `_renderIbkrSubagentPanel()` にstale検知追加。3日超で黄色バナー + カードタイトルに「⚠ N日前」バッジ表示 | ✅ デプロイ済み |
| 10 | 設計整理 | IBKRセクションがhealth/agents/overviewに分散 | 「IBKR 米株📈」タブを新設（stocksとscannerの間）。`renderIbkr()`を実装（ステータスカード + opsStatusCard compact + サブエージェントパネル）。stocksタブからサブエージェントパネルを分離 | ✅ デプロイ済み |
| 14 | 設計整理 | タブ名が不明確 | health→「監査・点検」/ scanner→「スキャン結果」/ outcome→「勝率分析」/ weekly-compare→「週次レポート」にリネーム | ✅ デプロイ済み |

### ✅ Step 3 — 完了（2026-05-16）

| No | 分類 | 問題 | 対応 | 状態 |
|----|------|------|------|------|
| 5 | UI改善 | タブ15個で初見に迷う | SECTIONS を5グループに再編（ホーム/取引システム/シグナル分析/市場情報/システム）。newsも市場情報グループ末尾に移動 | ✅ デプロイ済み |
| 7 | 表示改善 | タブ名が不明確 | Step2で完了済み（スキャン結果/勝率分析/週次レポート） | ✅ Step2完了 |
| 9 | 高速化 | CoinGecko market データが60秒ごとに再取得 | `_marketTimer` を 60s → 300s（5分）に延長。ローカルJSON(30s)/OHLC(5min)/ニュース(10min)/価格履歴(1h)は変更なし | ✅ デプロイ済み |

### ✅ Step 4 quick wins — 完了（2026-05-16）

| No | 分類 | 問題 | 対応 | 状態 |
|----|------|------|------|------|
| 4 | 未使用削除 | `isVmTailscaleHost()` 関数が未使用 | 削除（呼び出しなし確認済み） | ✅ デプロイ済み |
| 15 | UI整理 | newsタブが上位に表示されていた | 市場情報グループの末尾（market→news順）に配置済み（No.5と同時対応） | ✅ デプロイ済み |

### ✅ 追加改善B — タブバッジ 完了（2026-05-16）

| 内容 | 対応 | 状態 |
|------|------|------|
| タブナビにエラー通知ドットを表示 | `_getTabBadge(id)` を実装。IBKR未接続→赤点、IBKR要smoke/損失限界70%超え→黄点、Ouroborosボット停止→赤点、監査・点検に警告→黄点 | ✅ デプロイ済み |

### ✅ 追加改善 A・C・E — 完了（2026-05-16）

| 内容 | 対応 | 状態 |
|------|------|------|
| A: IBKR緊急停止コマンド表示 | IBKRタブ末尾に「⛔ 緊急停止」カードを追加。① ibkr_enabled=0 変更コマンド ② systemd stop コマンドをコピーボタン付きで表示 | ✅ デプロイ済み |
| C: IBKR追加状態表示 | IBKRステータスカードにセカンドロウ追加。VIX値（閾値30で色変化）/ 今日の選択銘柄 / SLクールダウン状態を表示 | ✅ デプロイ済み |
| E: 最終更新インジケーター | topbarの時刻表示を「更新 X分前」形式に変更（`ts2ago()` 利用） | ✅ デプロイ済み |

### ✅ Chart AI 統合 — 完了（2026-05-16）

| 内容 | 対応 | 状態 |
|------|------|------|
| IBKRタブに Chart AI シグナルセクション追加 | `_renderChartAiSection()` を実装。`/local_ai/chart_ai/chart_ai_score.json` を定期取得。LONG/SHORT/NEUTRAL シグナルをHIGH CONF優先で4列グリッド表示。48時間超で stale 警告。IBKRステータスカードの直下に配置。 | ✅ デプロイ済み |

### ✅ モバイル最適化F — 完了（2026-05-16）

| No | 分類 | 対応 | 状態 |
|----|------|------|------|
| F | UI | topbar pills/タイムスタンプをモバイル(≤680px)で非表示。.nav-item min-height: 44px（Apple HIG準拠タップ領域）。.card overflow-x: auto でテーブルの横スクロール対応。env(safe-area-inset-bottom) でiPhone X+ホームインジケーター対応。≤480px でmetric値18px・カードパディング縮小 | ✅ デプロイ済み |

### 🔲 残タスク（優先度C）

| No | 分類 | 問題 | 改善案 |
|----|------|------|--------|
| 8 | 保守性 | インラインスタイル多数で保守困難 | CSSクラス化（段階的）— 高難易度につき後回し |

---

## 触ると危険な箇所

| 箇所 | なぜ危険か |
|------|-----------|
| `manualRefresh()` / `startAutoRefresh()` | 全データ取得ロジックの起点。修正すると全タブに影響 |
| `fetchOpsStatus()` | 14ファイルを並列取得。エラーハンドリングを壊すと全データが落ちる |
| LocalStorage書き込み (`saveConfig`等) | スキーマ変更すると既存設定が読めなくなる |
| `renderSection()` の try-catch | これを外すと1タブのエラーが全体に波及 |
| `runKeibaWeeklyPredictionAction()` | 実際にAI予測スクリプトをVMで実行する |
| `submitPaperOrder()` | Paper APIが再起動した場合に実注文が走る |

---

## 現状 vs 理想構成ギャップ

| 理想タブ | 対応する現タブ | 状態 |
|----------|--------------|------|
| ホーム | overview | ✅ ほぼ対応。IBKRカード追加済み（Step1） |
| 運用状況 | ouroboros | ✅ BTC対応。IBKRはhealthに混在 |
| 監査・点検 | health | ✅ 対応。ラベルが「ヘルス」（Step2-14でリネーム予定） |
| レポート | outcome + weekly-compare + charts | △ 分散している |
| 設定 | alerts の一部 + config panel | △ 専用タブなし |
| 開発・保守 | agents | △ LLM評価のみ。エラーログなし |
| IBKR専用 | ibkr タブ（新設） | ✅ 独立タブ完成（Step2-10完了） |

---

## 既知の未生成ファイル（fetch先が存在しない）

| ファイル | 状況 |
|----------|------|
| `review_out/ibkr_vm_sync_status.json` | 未生成。fetchはNO-OPになっている |
| `review_out/stale_artifact_review_latest.json` | 生成スクリプトあり（`tools/stale_artifact_review.py`）、初回実行が必要 |
