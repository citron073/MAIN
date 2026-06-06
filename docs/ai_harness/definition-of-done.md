# Definition Of Done

変更完了は、少なくとも次を満たすこと。

- `docs/ai_harness/current_spec.md` の受け入れ条件を満たしている。
- 変更範囲が `docs/ai_harness/constraints.md` に収まっている。
- `docs/ai_harness/ouroboros_quality_gate.md` の該当ゲートを満たしている。
- `./scripts/validate.sh fast` が成功している。
- trading / widget / reflection に触れた場合は `./scripts/validate.sh trade` が成功している。
- 失敗した検証を無視していない。失敗が残る場合は理由と残リスクを書く。
- 秘密情報、トークン、APIキーをログや差分へ出していない。
- VMへ反映した場合は、反映ファイル、再起動サービス、確認結果を書く。
- Scriptable widgetを変えた場合は、exportとiCloudコピーの有無を書く。
