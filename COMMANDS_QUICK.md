# Ouroboros 毎朝5分チェック（超短縮版）

このファイルは「今日の運用を安全に始める」ための最短手順です。

## iPhone固定URL
```text
http://100.66.216.5:8793/tools/unified_dashboard.html
```

TailscaleをONにして開きます。これはVM直結URLなので、MacBookを閉じてもVM側の dashboard / Daily Ops / IBKR watch は継続します。Mac側Tailscaleが未接続でも、iPhoneのTailscaleがONならこのURLを使います。

稼働確認と0行ログ分類:
```bash
python3 tools/unified_dashboard_healthcheck.py
python3 tools/trade_log_zero_day_review.py
python3 tools/daily_ops_check.py  # dashboard/0行ログ/IBKR/バージョン整合性をまとめて保存

# Daily OpsでIBKRが「smoke再実行」なら、IB Gateway Paper起動後に読むだけの確認
# ダッシュボードの「IB Gateway」と「IBGW/TWS 7497」がOKになってから実行
python3 test_ibkr_connection.py --stocks AAPL,MSFT,NVDA,TSLA,QQQ,SPY --fx USDJPY

# IB Gatewayが落ちた時の読み取り専用watchを確認（注文は出さない）
python3 tools/ibkr_gateway_watch.py --dry-run

# 8793 + Daily Opsの毎日ヘルスチェックを自動化
./tools/install_unified_dashboard_healthcheck_launchagent.sh

# IB Gateway watchを5分ごとに自動化（ntfy設定済みなら異常/復旧だけ通知）
./tools/install_ibkr_gateway_watch_launchagent.sh

# SIGNAL_ONLY 候補抽出（注文なし）
python3 signal_scanner_weekly.py --dry-run
python3 signal_scanner_weekly.py --fx-only
python3 signal_scanner_outcome.py
systemctl list-timers --all | grep -E 'signal-scanner-(daily|weekly)|signal-outcome'
```

注意:
- MacBookを閉じてスリープすると、LaunchAgent / IB Gateway / watch は基本的に止まります。
- 閉じたまま継続したい場合は、電源接続 + 外部ディスプレイ等のクラムシェル運用、またはスリープさせない運用が必要です。
- VM側のbot自体はMacを閉じても影響しません。Mac側IB Gateway監視と株価読み取りだけが止まります。

VM側へIB Gatewayを寄せる準備チェック:
```bash
python3 tools/vm_ibkr_gateway_readiness.py

# 実VMを読み取り専用で確認
python3 tools/vm_ibkr_gateway_readiness.py \
  --host 161.33.26.35 \
  --key /Users/tani/.ssh/ouroboros_vm_key

# VM側IB Gatewayに安全に接続確認する時は公開ポートではなくSSHトンネルを使う
./tools/open_vm_ibkr_tunnel.sh \
  --host 161.33.26.35 \
  --key /Users/tani/.ssh/ouroboros_vm_key

# 別ターミナルで読み取り専用smoke
python3 test_ibkr_connection.py --host 127.0.0.1 --port 17497 --client-id 11 --stocks AAPL,MSFT,NVDA,TSLA,QQQ,SPY --fx USDJPY
```

VMへ監視/ダッシュボード更新を寄せる:
```bash
cd ~/trading_bot/trading_bot/MAIN
./tools/deploy_vm_dashboard_ops.sh \
  --host 161.33.26.35 \
  --key /Users/tani/.ssh/ouroboros_vm_key \
  --apply

ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 \
  'cd /home/ubuntu/trading_bot/MAIN && python3 tools/daily_ops_check.py --url http://127.0.0.1:8793/tools/unified_dashboard.html --timeout-sec 15'
```

VM Tailscale確認:
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 \
  'tailscale status --self && tailscale ip -4 && curl -sS -I --max-time 5 http://127.0.0.1:8793/tools/unified_dashboard.html | head -n 1'

# iPhoneから開く
# http://100.66.216.5:8793/tools/unified_dashboard.html
```

VM KEIBA確認:
```bash
# iPhone / Tailscale
# http://100.66.216.5:8511
# http://100.66.216.5:8789/keiba-status.json

ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 \
  'systemctl is-active ouroboros-keiba-streamlit.service ouroboros-keiba-status-server.service && curl -sS http://127.0.0.1:8511/_stcore/health && echo && curl -sS http://127.0.0.1:8789/health'
```

詳細の引き継ぎ情報は `MAIN/HANDOVER.md` / `MAIN/HANDOVER.json`、簡易ステータス面は `MAIN/WIDGETS.md` を参照。
売買ロジックの実装表は `MAIN/docs/OUROBOROS_TRADING_SPEC_TABLE.md` を参照。

## 0. 移動
```bash
cd ~/trading_bot/trading_bot/MAIN
```

## 0-U. Unified Dashboard
```bash
# file:// ではなくこのURLで開く
./tools/start_unified_dashboard.sh
# http://127.0.0.1:8792/tools/unified_dashboard.html?v=...

# iPhone / LAN / Tailscale から開く
./tools/start_unified_dashboard.sh --public
# 表示された LAN= または Tailscale= のURLをiPhoneで開く

# iPhone / Tailscale限定で開く（おすすめ）
./tools/start_unified_dashboard.sh --tailscale --port 8793

# Mac起動時に自動起動
./tools/install_unified_dashboard_launchagent.sh --mode tailscale --port 8793
```

設定が触れない場合は、画面内の `接続設定ショートカット` から Widget URL と Bearer Token を保存します。
外出先のiPhoneはTailscale URLを使うのが安全です。LaunchAgentを外す場合は `./tools/uninstall_unified_dashboard_launchagent.sh` を使います。画面の `Health` でDashboard Buildとlast validateを確認できます。

## 0-H. AIハーネス最短チェック
```bash
# DRAFT中の文書構成チェック
python3 tools/harness_quality_check.py --allow-draft

# note CMS 中央統括の簡易ヘルス
python3 tools/note_cms_healthcheck.py

# specテンプレ一覧
python3 tools/harness_spec_template.py --list

# shadow昇格候補の確認
python3 tools/shadow_promotion_report.py

# CONTROL/ai_model反映後の実効設定だけ確認（書込なし）
python3 tools/effective_config_dump.py
python3 tools/effective_config_dump.py --snapshot-dir .local_llm/vm_snapshot/latest

# main/shadow/特徴量/実効設定の総合レビュー（ローカルのみ）
python3 tools/trade_system_review.py
python3 tools/trade_system_review.py --write
python3 tools/trade_system_review.py --snapshot-dir .local_llm/vm_snapshot/latest --write

# 日次反省/LLM fallbackの確認
python3 tools/llm_reflection_audit.py

# VMに影響しないローカルLLM助言（読み取り専用snapshot）
python3 tools/local_llm_healthcheck.py
./tools/sync_vm_llm_inputs.sh
python3 tools/local_llm_trade_review.py --snapshot-dir .local_llm/vm_snapshot/latest

# まとめて実行
./tools/run_local_llm_review.sh
```

実装前に `docs/ai_harness/current_spec.md` を `Status: READY` にした場合:
```bash
python3 tools/harness_quality_check.py
./scripts/validate.sh fast
```

## 0-0. バージョン最小確認
```bash
python3 yt_tool.py --version
python3 - <<'PY'
import json, pathlib, re
import bot
root = pathlib.Path(".")
dashboard = re.search(r'APP_VERSION = "([^"]+)"', (root / "dashboard.py").read_text(encoding="utf-8")).group(1)
widget = re.search(r'WIDGET_SERVER_VERSION = "([^"]+)"', (root / "tools/widget_status.py").read_text(encoding="utf-8")).group(1)
handover = json.load(open(root / "HANDOVER.json", encoding="utf-8"))
print("bot.version =", bot.OUROBOROS_BOT_VERSION)
print("feature.schema =", bot.OUROBOROS_FEATURE_SCHEMA_VERSION)
print("dashboard.version =", dashboard)
print("widget.version =", widget)
print("mr_observe.phase =", "phase1.5-a-rank-paper")
print("handover.updated_at_jst =", handover["meta"]["updated_at_jst"])
PY

# bot.py / HANDOVER / SPEC表 / テストのバージョン整合
python3 tools/version_consistency_check.py

# stale成果物の棚卸し（削除しない）
python3 tools/stale_artifact_review.py

# stale成果物のarchive移動 plan（既定dry-run）
python3 tools/archive_stale_artifacts.py

# IBKR adapter import監査（paper-order層の呼び出し元を確認）
python3 tools/ibkr_import_audit.py
```

## 0-0A. チャート/OHLC実装確認
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

A/B/C局面の主な設定:
```text
market_phase_enabled=1
market_phase_block_b_enabled=0   # 既定。B局面を記録だけして、強制停止はしない
ai_use_market_phase=1
trade_notify_market_phase_enabled=1
```

B局面をshadowで強制回避テストする場合:
```text
market_phase_block_b_enabled=1
```

TP寸前戻しのshadow早逃げ検証:
```text
near_tp_giveback_exit_enabled=1
near_tp_giveback_exit_only_paper=1
near_tp_giveback_exit_trigger_ratio=0.85
near_tp_giveback_exit_min_giveback_pct=0.04
near_tp_giveback_exit_max_current_fav_pct=0.06
```

相場流 Phase 1 の観測:
```text
aiba_style_enabled=1
aiba_style_ai_enabled=0   # まずはログ観測だけ。AI反映はshadow検証後
aiba_ma_short_n=5
aiba_ma_mid_n=20
aiba_ma_long_n=60
aiba_nine_rule_alert_n=9
aiba_try_fail_min_count=2
```

VM側の実行間隔確認:
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 \
  'systemctl show -p ExecStart --value ouroboros-bot.service; systemctl show -p ExecStart --value ouroboros-shadow.service; systemctl show -p ExecStart --value ouroboros-mr-observe.service'
```

## 0-1. VM接続先（再作成後）
```bash
VM_HOST=161.33.26.35
VM_KEY=/Users/tani/.ssh/ouroboros_vm_key
```

再開時の最小確認（VM側）:
```bash
cd ~/trading_bot/trading_bot/MAIN
pwd
sudo systemctl cat ouroboros-drift-watch.service | grep ExecStart
sudo systemctl cat ouroboros-weekly-autotrain.service | grep ExecStart
sudo systemctl cat ouroboros-trade-notifier.service | grep ExecStart
sudo systemctl cat ouroboros-widget-status.service | grep ExecStart
sudo systemctl cat ouroboros-morning-start-check.service | grep ExecStart
```

## 0-2. Ubuntuクラウド一括セットアップ（初回のみ）
```bash
chmod +x ./tools/cloud_ubuntu_setup.sh
./tools/cloud_ubuntu_setup.sh --with-secrets
```

## 1. ダッシュボード起動
```bash
./tools/start_dashboard_ngrok.sh
```

簡易ステータス面だけ見る場合:
```bash
python3 tools/widget_status.py --print-text
WIDGET_STATUS_HOST=0.0.0.0 ./tools/start_widget_status_server.sh
```

iPhone の Scriptable を更新する最短:
```bash
./tools/publish_scriptable_widget.sh
```

PCを閉じていても見たい場合は、VM側で:
```bash
echo "WIDGET_STATUS_TOKEN='change-this-token'" | sudo tee -a /etc/ouroboros/secrets.env
sudo chmod 600 /etc/ouroboros/secrets.env
./tools/install_systemd_services.sh --with-widget-status
sudo systemctl restart ouroboros-widget-status.service
curl "http://127.0.0.1:8787/widget-status.json?token=change-this-token"
```

## 2. 事前チェック（LIVE前）
```bash
python3 tools/live_preflight.py
./run_check.sh
./tools/safe_guard.sh
python3 tools/morning_start_guard.py --print-json
```

Cloud/Linux で secrets 未設定なら先に:
```bash
sudo ./tools/register_cloud_secrets_env.sh /etc/ouroboros/secrets.env
```

## 3. ダッシュボードで確認
1. `🏠 ホーム・稼働状況`
2. `🚀 実行・緊急操作` の `起動前セーフティゲート`
3. `⚙️ Bot設定` の重要値

重要値（推奨）:
- `safety_hard_block=0`（運用する日）
- `daily_loss_limit_pct=-1.0`（またはより厳しめ）
- `ai_train_include_shadow=1`
- `ai_gate_enabled=1`
- `ai_auto_rollback_enabled=1`

## 4. 起動
ダッシュボードで  
`🚀 実行・緊急操作` → `bot起動 (1/2)` → `bot起動 (2/2)`

CLIで起動する場合:
```bash
./tools/safe_start_bot.sh
# LIVE候補時だけ
./tools/safe_start_bot.sh --allow-live
```

朝の自動再開を入れる場合:
```bash
./tools/install_systemd_services.sh --with-morning-start-check
sudo systemctl restart ouroboros-morning-start-check.timer
sudo journalctl -u ouroboros-morning-start-check.service -n 40 --no-pager
```

## 5. 監視（運用中）
- `🏠 ホーム`: risk_stop / streak_stop / 資金
- `🧪 Shadow起動/停止`: 影運用が生きているか
- `logs/instances/mr_observe/`: MR observe の件数、note品質、`mr_paper_entries_total`
- `📊 成績・分析`: 日次生成と監査

## 6. 停止（通常）
ダッシュボードで  
`bot停止 (1/2)` → `bot停止 (2/2)`

必要なら `停止時に未決済LIVEポジを強制エグジット` をON

CLIで停止する場合:
```bash
./tools/safe_stop_bot.sh
```

## 7. 緊急停止
ダッシュボードで  
`🚨 一括停止 (1/2)` → `🚨 一括停止 (2/2)`

## 8. よくある障害（即対応）
### ngrok offline
```bash
pkill -f ngrok || true
./tools/start_dashboard_ngrok.sh
```

### ダッシュボード常駐を入れ直す
```bash
./tools/uninstall_dashboard_launchagent.sh
pkill -f ngrok || true
./tools/install_dashboard_launchagent.sh
```

### commit履歴を自動記録（初回のみ）
```bash
./tools/install_git_post_commit_hook.sh
```

---
詳細手順は `MAIN/COMMANDS.md` を参照。
