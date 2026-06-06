# OuroborosWidgetNative Setup Checklist

このチェックリストは、`OuroborosWidgetNative` を iPhone 実機へ入れる時に詰まりやすい項目を順番に潰すためのものです。

## 0. 前提

- full Xcode が必要です
- `xcodebuild` ではなく `Xcode.app` 本体を使います
- この native app は売買ロジックを持たず、既存の Web 経路を安全に包む shell です

プロジェクト:

- `MAIN/widget_native_ios/OuroborosWidgetNative/OuroborosWidgetNative.xcodeproj`

## 1. Xcode を入れる

確認:

```bash
ls -d /Applications/Xcode.app
```

無ければ:

1. App Store から `Xcode` を入れる
2. 初回起動してライセンス同意と追加コンポーネントを完了する

必要なら開発ツールを Xcode 本体へ切り替えます。

```bash
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
```

## 2. プロジェクトを開く

Finder か Xcode から以下を開きます。

- `MAIN/widget_native_ios/OuroborosWidgetNative/OuroborosWidgetNative.xcodeproj`

## 3. Signing & Capabilities

ターゲット:

- `OuroborosWidgetNative`

設定するもの:

1. `Team` を自分の Apple Developer / Personal Team にする
2. `Bundle Identifier` が衝突する場合は少し変える
   - 例: `com.ouroboros.widgetnative.tani`
3. `Signing Certificate` は自動で問題ありません

詰まりやすい症状:

- `No signing certificate`
  - Xcode の `Settings / Accounts` で Apple ID を追加
- `Bundle Identifier already in use`
  - Bundle Identifier を少し変える
- `Provisioning profile` エラー
  - Team を選び直し、`Automatically manage signing` を維持

## 4. iPhone 実機へ入れる

1. iPhone を Mac に接続
2. Xcode 上部の Run Destination で iPhone を選ぶ
3. 初回は iPhone 側で `開発者モード` や `このコンピュータを信頼` の確認が出る場合があります
4. `Run` で起動

詰まりやすい症状:

- `Developer Mode required`
  - iPhone の設定で開発者モードを有効にする
- `Could not launch`
  - iPhone を再接続し、ロック解除した状態で再実行
- `Untrusted Developer`
  - iPhone の `設定 > 一般 > VPNとデバイス管理` で署名元を信頼

## 5. 初回設定

App を起動したら `Settings` タブで以下を設定します。

- Host 例: `http://100.66.216.5`
- Token: widget 用 token

注意:

- `Overview / Reflection` は token 必須
- `Dashboard` は token 不要
- token は repo に保存されず、端末内の `AppStorage` だけに保存されます

## 6. 動作確認

順番:

1. `Overview`
2. `Reflection`
3. `Dashboard`
4. ホーム画面ウィジェット
5. ロック画面ウィジェット
6. Native通知

最低確認:

- `Overview` が通常Overview表示で開く
- `Reflection` がホーム画面トーンの反省表示で開く
- `Overview / Reflection` の中に、Web確認用の上部タイトル・scene切替・iPhoneモック枠が出ていない
- `Dashboard` へ遷移できる
- ホーム画面に `Ouroboros` の Small / Medium Widget を追加できる
- ロック画面に `Ouroboros` の Circular / Rectangular / Inline Widget を追加できる
- 配置済みWidgetを長押しして `ウィジェットを編集` を開き、`表示内容` を `自動 / 口座 / シャドウ / 日次 / 週次` から選べる
- `自動` の場合、Smallは日次、Mediumは口座、ロック画面系は `RUN ON/OFF` を優先して表示する
- ホーム画面Medium Widgetが枠いっぱい寄りに表示され、口座/週次/ドリフトの小カードが見える
- `Settings` で `Native通知を有効化` をONにできる
- `通知許可を確認` でiOS通知権限を確認できる
- `テスト通知を送る` で通知が出る
- `Free Push / ntfy` に topic URL を入れ、`ntfyテスト送信` で無料Push経路を確認できる
- オフライン時に真っ白ではなく最低限の表示になる

Widgetが出ない場合:

- アプリを一度起動して `Settings` の Host/token を保存する
- Xcodeの `Signing & Capabilities` で App本体とWidget Extensionの両方に App Groups を追加する
- App Group ID は `group.com.ouroboros.widgetnative`
- 追加後、iPhone上のアプリを削除してから再Runすると反映が早い場合があります

## 7. オフライン確認

iPhone 実機でこの順に確認します。

1. `Overview` を開く
2. いったんホームへ戻る
3. 機内モード ON
4. 再度 app を開く

期待値:

- 完全な最新値ではなくてもよい
- `オフライン表示中` の文脈が見える
- 白画面にならない

## 8. うまくいかない時の切り分け

### A. native app は起動するが Overview が見えない

- Host が `http://100.66.216.5` になっているか
- token が入っているか
- iPhone の Tailscale が ON か

### B. Dashboard だけ見えない

- `http://100.66.216.5:8793/tools/unified_dashboard.html` が iPhone Safari で開けるか

### C. Overview / Reflection だけ 401

- token 不一致の可能性が高いです
- token を入れ直して再確認

### D. 画面が古い

- app を一度終了して再起動
- それでも古ければ `Overview` を pull-to-refresh 代わりに再読み込み

## 9. 安全境界

この native app は以下をしません。

- 注文実行
- token の repo 保存
- 売買ロジックの変更
- CONTROL.csv / state.json の直接更新

役割は「既存の安全な Web 経路を iPhone 用に包むこと」です。
