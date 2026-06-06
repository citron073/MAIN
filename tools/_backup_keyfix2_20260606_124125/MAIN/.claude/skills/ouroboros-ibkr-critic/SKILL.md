---
name: ouroboros-ibkr-critic
description: IBKR米株取引ボットの週次パフォーマンス評価。100点減点方式でスコアリングし、パラメータ改善を自動適用する。
disable-model-invocation: false
---

# /ibkr — Ouroboros IBKR 週次評価

このスキルが呼ばれたら `ouroboros-ibkr-critic` サブエージェントを起動して以下を実行する。

## 手順

1. VMで評価スクリプトを実行してレポートを生成する:
   ```bash
   ssh -i /Users/tani/Downloads/ssh-key-2026-03-04-4.key ubuntu@161.33.26.35 \
     "cd /home/ubuntu/trading_bot/MAIN && python3 tools/weekly_ibkr_critic.py"
   ```

2. `ouroboros-ibkr-critic` エージェントを起動してレポートを解釈・改善適用させる。

3. 結果をユーザーに verdict 形式で報告する。

## 引数

- 引数なし: 直近の完結週を評価
- `--week YYYYMMDD`: 指定週を評価（その週の月曜日を指定）
- `--dry-run`: 分析のみ、パラメータ変更なし

## 注意

- このスキルは自動で毎週日曜20時30分JST（systemdタイマー）にも実行される
- 手動実行で上書きしても問題ない（冪等）
