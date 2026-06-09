#!/bin/bash
# IBKR 2FA reminder — sent 5 minutes before Gateway timer fires
# Fires Mon-Fri 13:15 JST via ouroboros-ibkr-2fa-reminder.timer

NTFY_URL="https://ntfy.sh/ouroboros-Rdo5ZRinUQ5aIgZ6rZ4ghkla"

# Check whether Gateway is already running (skip reminder if connected)
if ss -tan | grep -q ':7496'; then
    echo "$(date +%F\ %T) Gateway already on port 7496 — skipping reminder" >> /home/ubuntu/ibgateway-headless-logs/2fa_reminder.log
    exit 0
fi

curl -s -X POST     -H "Title: IBKR 2FA 準備して"     -H "Priority: high"     -H "Tags: warning,closed_lock_with_key"     -d "あと5分 (20:50) で IB Gateway が起動します。iPhone IBKR Mobile アプリを開いて 2FA 通知の承認準備をしてください。承認しないと480秒でタイムアウト → 終日IBKR取引不可になります。"     "$NTFY_URL" > /dev/null

echo "$(date +%F\ %T) Reminder sent" >> /home/ubuntu/ibgateway-headless-logs/2fa_reminder.log
