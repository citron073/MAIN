# Widget Device Checklist

Scriptable Widgetを変えたら、iPhone実機でこの順に見る。

## 共通

- 通信成功時に真っ白にならない。
- 通信NG時に `通信NG` など短いエラーが出る。
- 古いJSON payloadでも落ちない。
- 色だけでON/OFFを伝えていない。
- 右上、下部、左端に不自然な空白または見切れがない。

## Small

- 最重要ステータスだけに絞れている。
- 目標/警告/稼働のどれか1つが主役になっている。
- 数字が切れていない。

## Medium

- 日次目標、pnl/残高、稼働、driftが読める。
- カード同士の高さが揃っている。
- 右上の空きは情報カードか意図的な余白として使う。
- 上下が見切れていない。

## Large

- 日次、週間、shadow、反省が読み分けられる。
- 情報が多すぎてmedium化していない。
- 下部の反省文が長すぎない。

## 更新手順

```bash
cd ~/trading_bot/trading_bot/MAIN
./tools/publish_scriptable_widget.sh
```

同期が怪しい場合は、Scriptable側で対象script名と更新時刻を見る。

