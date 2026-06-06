# Review Rubric

QAレビューは褒める場ではなく、不合格条件を探す場です。

詳細な昇格条件、UI基準、LLM/日次反省基準は `docs/ai_harness/ouroboros_quality_gate.md` も見ること。

## Trading Safety

- main実弾挙動が意図せず変わっていないか。
- shadow / observe で先に検証できる変更になっているか。
- shadow / observe からの昇格条件を満たす前にmainへ進めていないか。
- TP/SL、risk stop、streak stop、drift gate の優先順位が崩れていないか。
- `CONTROL.csv` と `CONTROL_shadow.csv` の責務が混ざっていないか。

## Data Contract

- 既存CSV列や `result` 名を壊していないか。
- daily report、widget status、trade notifier、auditが同じ意味で読めるか。
- payloadへ追加した値が欠損時にも安全に表示されるか。

## UI / Widget

- 小・中・大サイズで見切れないか。
- 右上や下部の空きがある場合、重要情報か安全な余白として意図的に使っているか。
- 右寄せ/中央寄せなどの調整が他サイズへ悪影響を出していないか。
- 日本語表示が短く、iPhoneのWidget幅で崩れないか。
- 「AIっぽい無難な見た目」より、情報の優先順位が明確か。

## React Frontend

- `pages/`、`components/ui/`、`components/feature/`、`lib/`、`services/`、`types/` の責務が混ざっていないか。
- 計算処理やAPI通信をcomponent内へ直書きしていないか。
- 既存Next.jsをViteへ勝手に移行していないか。
- 小さい部品やhooksへ過剰分割して読みにくくしていないか。
- 既存プロジェクトにある `lint`、`typecheck`、`test`、`build` を通したか。

## LLM / Reflection

- LLMが落ちてもルールベースfallbackで反省レポートが出るか。
- LLM出力がmain実弾設定を無確認で変更しないか。
- 勝因/敗因/翌日の推奨設定が短く構造化され、二重送信されないか。

## Tests

- 変更ロジックの成功ケースとブロックケースがあるか。
- テストが実装詳細に寄りすぎず、壊したくない契約を見ているか。
- 検証ログに失敗が残っていないか。

## Scope

- 仕様外の大きなリファクタを混ぜていないか。
- 依存追加なしで済むなら追加していないか。
- VM反映が必要な変更か、ローカルだけでよい変更かを分けているか。
