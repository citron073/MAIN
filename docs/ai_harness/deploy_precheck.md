# Deploy Precheck

VMへ反映する前に、この内容を埋めてから実行する。

## 反映前

- 対象VM:
- 反映ファイル:
- 再起動サービス:
- ローカル検証結果:
- 影響範囲: widget / notifier / shadow / main-live / docs-only
- rollback方法:

## 禁止

- 秘密情報を表示する。
- 未検証の変更をmain実弾へ反映する。
- 反映ファイル一覧なしでscpする。
- 再起動サービスを曖昧にしたまま進める。

## 反映後

- `sudo systemctl status <service>` を確認する。
- Widget/APIがある場合はJSONまたはテキスト表示を確認する。
- 反映したファイル、サービス、確認結果を作業メモに残す。

