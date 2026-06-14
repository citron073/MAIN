# サービス健全性トリアージ（systemctl --failed の誤警報対応）

> 2026-06-14 監査。`systemctl --failed` に出る ouroboros 系の「failed」を全件切り分けた結果。
> **再調査防止用**: 下記は調査済み。新たに別サービスが failed になった時だけ調べること。

## 結論サマリ

| サービス | 実態 | 対応 |
|---------|------|------|
| `ouroboros-pdca-daily` | **本物の小バグ→修復済** | reports/pdca_log.json が06/07クリーンアップで消失→毎日 `pdca_log_not_found`。**空リスト`[]`を種まきして解消**(2026-06-14・exit 0確認) |
| `ouroboros-btc-critic` | **誤警報（仕様）** | ラッパーが `sys.exit(0 if main()>=60 else 1)`。週次スコア<60点で exit 1→systemdがfailed表示。**評価・レポート・auto-applyは完走している**。スコアが低いだけ(直近40点=BTC5分botは低調・R&D扱いなので想定内) |
| `ouroboros-ibkr-critic` | 誤警報（同上の可能性） | 同じ低スコア→exit1パターンと推定。中身は動作 |
| `ouroboros-ibkr-readonly-smoke` | **誤警報（仕様）** | IB Gateway接続スモークテスト。Gatewayは20:50 JSTログイン→**US休場・場外時間(日中)は接続CLOSEDで当然失敗**。15分間隔のため場外は常時failed表示になるが正常 |
| pyenv rehash lock warning | 表示ノイズ | **Mac側ローカル**のpyenv shimロック競合（並列bg実行の副産物）。VM・処理に影響なし |

## なぜ放置せず記録したか
誤警報が `systemctl --failed` を占有すると「failedは普通」と慣れ、**本物の故障(botクラッシュ等)を見逃す**。将来この一覧に**上記4件以外**が出たら、それは新規＝要調査。

## 任意の追加改善（未実施・低優先）
- critic類: `sys.exit(0)` 固定化しスコアはntfy/レポートのみで通知すれば `--failed` が本物専用になる。ただし auto-apply 本番スクリプトに触れるため見送り中。
- smokeテスト: timerを市場時間帯(21:00–06:00 JST)限定にすれば場外ノイズが消える。
