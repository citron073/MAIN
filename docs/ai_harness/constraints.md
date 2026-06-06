# Harness Constraints

## 原則

- 仕様が `Status: READY` でない場合は実装しない。
- `docs/ai_harness/ouroboros_quality_gate.md` の該当ゲートを読む。
- 既存の `result` 意味、CSV列、daily report / audit の集計定義を壊さない。
- 変更は差分追加を優先し、全張り替えや大規模リライトを避ける。
- 秘密情報を表示、コピー、コミットしない。

## 通常編集してよい範囲

- `bot.py`
- `tools/*.py`
- `tests/*.py`
- `widget/scriptable/*.js`
- `docs/**`
- `scripts/**`
- `.vscode/tasks.json`
- `.claude/**`

## React / Frontend作業で編集してよい範囲

- 対象frontend rootは `current_spec.md` の `Allowed Files` に明記する。
- Vite新規UIなら `src/**`, `tests/**`, `public/**`, `package.json`, `tsconfig.json`, `vite.config.ts` を対象にできる。
- 既存Next.js UIなら、既存の `app/**`, `components/**`, `lib/**`, `public/**` へ合わせる。Vite構成へ無確認で移行しない。
- フォルダ責務は `docs/ai_harness/react_frontend_structure.md` を優先する。

## 明示確認が必要な範囲

- `CONTROL.csv` の本番制御値
- `.streamlit/secrets.toml`
- `/etc/ouroboros/secrets.env`
- `deploy/systemd/**`
- VM上のsystemd再起動、deploy、APIキー利用
- 依存追加や大規模アップデート

## 禁止

- `git reset --hard` などの破壊的操作。
- 未確認の本番DB migration。
- `rm -rf` など広範囲削除。
- テストを通すためだけの仕様逸脱やスタブ化。
- main実弾挙動の変更を shadow / observe 検証なしで入れること。

## 昇格ルール

- 新しい売買ロジックは原則 `shadow` または `observe` から始める。
- 昇格条件は `docs/ai_harness/ouroboros_quality_gate.md` の `Shadow / Observe 昇格条件` を優先する。
- mainへ上げる前に、日次ログ、shadow差分、テスト、リスク影響を確認する。
- ウィジェットや通知は、ログ/JSON payloadが先、表示は後の順で変更する。
