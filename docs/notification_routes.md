# Notification Routes

Project Ouroboros v1 の通知元、通知先、通知タイミングを運用者向けに一覧化する。

共通ヘルパー:

- `MAIN/tools/notification_policy.py`
  - `INFO / WARN / CRITICAL` の正規化
  - ntfy `Priority` / `Tags` の標準化
  - 通知 cooldown の共通化
  - 段階的に各通知元へ展開中

## Overview

| Source | File | Function / Entry | Channel | Level | Trigger | Notes |
|---|---|---|---|---|---|---|
| IBKR | `MAIN/ibkr_bot.py` | `_send_ntfy()` | ntfy | WARN / CRITICAL | Paper bot の異常・状態変化 | token は `secrets.toml` 読み取り |
| Weekly Report | `MAIN/tools/send_weekly_summary_ntfy.py` | `main()` | ntfy | INFO | 週次サマリ送信 | 週次 auto-train 後 |
| Smart Exit | `MAIN/tools/smart_exit_report.py` | `--ntfy` | ntfy | INFO / WARN | smart exit レポート送信 | 明示実行または timer |
| Event Notifier | `MAIN/tools/trade_event_notifier.py` | `_send_event()` 系 | ntfy / webhook | WARN / CRITICAL | drift変更、trade再開、DD悪化など | 一部 cooldown 実装あり |
| Dashboard | `MAIN/dashboard.py` | `_notify_control_change_ntfy()` | ntfy | INFO | CONTROL変更 | 差分通知 |
| Shadow Weekly | `MAIN/stock_shadow_weekly.py` | `send_notification()` | ntfy / webhook | INFO | 週次 shadow summary | notifier 未設定時はファイル保存へフォールバック |
| Shadow Readiness | `MAIN/stock_shadow_weekly.py` | `_send_readiness_achieved_notify()` | ntfy | CRITICAL | READY_FOR_LIVE 到達 | 実弾準備完了 |
| Shadow Trade | `MAIN/stock_shadow_bot.py` | `_send_trade_notify()` | ntfy | INFO | BUY / SELL / SHORT / COVER | 取引イベント |
| KEIBA Auto Cycle | `KEIBA/keiba_auto_cycle.py` | `_send_keiba_ntfy()` | ntfy | INFO / WARN / CRITICAL | 自動サイクル完了 / 失敗 / WR変化 | `KEIBA/data/auto_cycle_config.json` 優先 |
| KEIBA Public Watch Local | `KEIBA/keiba_public_watch.py` | `_notify_macos()` | macOS通知 | WARN | 公開監視イベント | `osascript` 利用 |
| KEIBA Public Watch Remote | `KEIBA/keiba_public_watch.py` | `_notify_remote()` | ntfy / webhook | WARN / CRITICAL | recovery / unhealthy / URL変化 | 公開監視向け, webhook payload に `event_level` を含む |

## Channel Rules

| Channel | Current State | Notes |
|---|---|---|
| ntfy | Primary | 公開 topic なら token 不要。URL は画面やログに出さない |
| macOS notification | Local helper | `KEIBA/keiba_public_watch.py` のみ |
| webhook | Partial | KEIBA public watch / shadow weekly で使用 |

## Shared Policy Rollout

現在 `notification_policy.py` を利用している通知元:

- `MAIN/tools/send_weekly_summary_ntfy.py`
- `MAIN/tools/smart_exit_report.py`
- `MAIN/signal_scanner_outcome.py`
- `MAIN/stock_shadow_weekly.py`
- `MAIN/stock_shadow_bot.py`
- `MAIN/ibkr_bot.py`
- `KEIBA/keiba_auto_cycle.py`
- `KEIBA/keiba_public_watch.py` の ntfy 部分

独自実装を残している通知元:

- `MAIN/tools/trade_event_notifier.py`
  - 既存 cooldown ロジックを基準実装として保持
- `KEIBA/keiba_public_watch.py`
  - macOS通知 + webhook は独自実装を維持
  - ntfy の level / tags は `notification_policy.py` を利用

## Widget Side

| Item | Path | Role |
|---|---|---|
| Widget server | `MAIN/tools/widget_status.py` | `state.json` / `CONTROL.csv` / `secrets.toml` を読み、`/widget-status.json` と `/widget-app` などを返す |
| Widget guide | `MAIN/WIDGETS.md` | 実運用ガイド兼 widget 仕様メモ |
| Scriptable local | `MAIN/widget/scriptable/OuroborosWidget.local.js` | ローカル / LAN / VM 向け |
| Scriptable shared | `MAIN/widget/scriptable/OuroborosWidget.js` | 配布用 |

## Guardrails

- 通知URLや bearer token を JS 側へ直書きしない
- secrets の中身をログに出さない
- widget は表示専用で、注文や取引判断を持たない
- dashboard から archive apply は実行しない
