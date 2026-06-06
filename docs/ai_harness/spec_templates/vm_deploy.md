# VM Deploy Spec Template

Status: READY

## Goal

- ローカルで検証済みの変更をVMへ安全に反映する。

## Input

- 反映対象ファイル:
- 対象VM:
- 再起動サービス:

## Output

- scp対象:
- systemd確認結果:
- rollback手順:

## Constraints

- `docs/ai_harness/constraints.md` を必ず守る。
- 秘密情報、APIキー、トークンを表示しない。
- deploy前に `docs/ai_harness/deploy_precheck.md` を見る。

## Pre-Implementation Contract

- Allowed Files: docs/**, deploy/**, tools/deploy_*.sh
- Runtime Impact: VM deploy
- Data Contract: ランタイムpayload/CSV/resultを変更する場合は事前に明記。
- Safety Gate: report-only
- Validation: trade
- Rollback: 反映前ファイルをバックアップし、対象サービスを元に戻す。

## Acceptance Criteria

- [ ] 反映ファイル一覧が明記されている。
- [ ] 再起動サービス一覧が明記されている。
- [ ] ローカル `./scripts/validate.sh trade` が成功している。
- [ ] VM反映後に `systemctl status` またはWidget/API確認を実施する。

## Out Of Scope

- 秘密情報の表示。
- 無確認のsystemd変更。

