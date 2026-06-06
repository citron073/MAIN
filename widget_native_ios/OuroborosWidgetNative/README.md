# OuroborosWidgetNative

`OuroborosWidgetNative` は、ZIP React完全移植版の `widget-react` / `unified dashboard` を安全に包む iPhone 向け native shell です。

## 目的

- 既存の売買ロジックや token 保護を変更しない
- iPhone から `Overview / Reflection / Dashboard` を native app で開けるようにする
- 設定値は repo に直書きせず、app 内の `Settings` タブに保存する

## 構成

- `Overview`: `:8787/widget-react/index.html?token=...&scene=overview&native=1`。通常Overview表示
- `Reflection`: `:8787/widget-react/index.html?token=...&scene=reflection&native=1`。ホーム画面トーンの反省表示
- `Dashboard`: `:8793/tools/unified_dashboard.html`
- `Settings`: Host と token をローカル保存。Native通知のON/OFFとテスト通知もここで扱う
- `OuroborosWidgetNativeWidget`: WidgetKit Extension。ホーム画面/ロック画面ウィジェットを提供
- `Command`: native app 専用の管制室。`/widget-status.json` を直接読み、口座/日次/週次/Shadow/診断/通知履歴/Widgetプリセットを表示
- `Live Activity`: Command から手動開始/更新/終了するロック画面・Dynamic Island 用の稼働ステータス表示

## 使い方

1. Mac で `MAIN/widget_native_ios/OuroborosWidgetNative/OuroborosWidgetNative.xcodeproj` を Xcode で開く
2. `Signing & Capabilities` で自分の Team を設定する
3. iPhone 実機を選んで起動する
4. App の `Settings` タブで以下を入れる
   - Host 例: `http://100.66.216.5`
   - Token: widget 用 token
5. `Command / Overview / Reflection / Dashboard` を順に確認する

詰まりやすい項目は [SETUP_CHECKLIST.md](/Users/tani/trading_bot/trading_bot/MAIN/widget_native_ios/OuroborosWidgetNative/SETUP_CHECKLIST.md) を参照してください。

## 注意

- native app 自体は新規の売買機能を持ちません
- token は repo に保存せず、端末内 `AppStorage` にだけ保存します
- `Overview / Reflection` は token 必須、`Dashboard` は token 不要です
- `Overview / Reflection` は `native=1` を付け、Web側の確認用ヘッダーやiPhoneモック枠を非表示にします
- `Overview / Reflection` 内の Balance / Daily Goal / Weekly / Ops は、mockではなく現在の `widget-status.json` から生成します
- Native通知はアプリ内で権限を取り、Web表示失敗時に30分抑制でローカル通知します
- Command Center は `Settings` でFace ID/パスコード保護をONにできます
- Command Center の `診断する` は Widget JSON / Dashboard / Runner / Trade / Shadow を読み取り専用で確認します
- Command Center の `Notification Log` は、Web表示失敗、通知テスト、ntfyテスト、Widget更新の履歴を端末内に保存します
- Command Center の `Live Activity` は、ロック画面/Dynamic Island に `Trade / Runner / Balance / Daily / Weekly / Shadow` を凝縮表示します
- 無料の外部Pushは `ntfy` を使います。Settings に `ntfy_topic_url` 相当を保存し、テスト送信と購読ページ起動ができます
- 完全な独自バックグラウンドPush通知は、APNs/サーバー側の追加が必要です。現段階では無料で運用しやすい `ntfy` を正ルートにします
- WidgetKit Extension は `Settings` の Host/token を App Group で共有し、`/widget-status.json` を読みます
- 対応Widget: ホーム画面 `Small / Medium`、ロック画面 `Circular / Rectangular / Inline`
- Widgetはサイズごとに表示密度を変えます。`Small` は黒い口座カード風、`Medium` は口座/Cash/週次/ドリフトの詳細カード、ロック画面系は円形ドーナツと横長ピルの凝縮表示です
- Widget配置後に長押しして `ウィジェットを編集` を開くと、表示内容を `自動 / 口座 / シャドウ / 日次 / 週次` から選べます
- ホーム画面Widgetは標準マージンを無効化し、添付デザインの `OB / Ouroboros / Balance / Donut / Cash-Health-Energy` に寄せています
- ロック画面Widgetの `自動` は、円形ではドーナツ中心、横長ではグレーのピル表示で口座額と当日%を出します
- `scene=lock` と `scene=standby` はURL指定用として残していますが、native app の通常タブには出しません

## Live Activity / Dynamic Island

1. iPhone の `設定 > Ouroboros > Live Activities` が有効になっていることを確認する
2. App の `Settings` で Host/token を保存する
3. App の `Command` タブを開く
4. `Live Activity` の `開始` を押す
5. 状態が変わったら `更新`、不要になったら `終了` を押す

現状は無料で使える手動更新版です。APNs を使った完全な自動バックグラウンド更新は、Apple Developer 側の Push 設定とサーバー追加が必要なので未実装です。

表示内容:

- ロック画面: RUN状態、口座額、日次、週次、Shadow、更新時刻
- Dynamic Island: compact では ON/OFF と週次、expanded では口座/日次/週次/Shadow を表示
- 売買判断や注文実行は行わず、`/widget-status.json` の読み取り結果だけを表示します

## ホーム画面/ロック画面ウィジェット

1. XcodeでアプリをiPhoneへRunする
2. アプリの `Settings` で Host/token を設定する
3. ホーム画面を長押しして `Ouroboros` ウィジェットを追加する
4. ロック画面のカスタマイズから `Ouroboros` の丸/横長/インライン表示を追加する
5. 必要なら配置済みWidgetを長押しし、`表示内容` を `自動 / 口座 / シャドウ / 日次 / 週次` から選ぶ

注意:

- 初回はWidgetが `SettingsでHost/tokenを設定` と出る場合があります。その場合はアプリを一度開いてSettingsを保存し直してください
- `Signing & Capabilities` で App Groups の `group.com.ouroboros.widgetnative` が必要です。Xcodeが警告した場合は、アプリ本体とWidget Extensionの両方で同じApp Groupを有効化してください
- `自動` はサイズ別に最適化します。ホーム画面は口座カード、ロック画面は口座/シャドウ状態を凝縮表示します

## Native通知

1. App の `Settings` を開く
2. `Native通知を有効化` をONにする
3. 必要なら `Command CenterをFace IDで保護` をONにする
4. `通知許可を確認` を押してiOSの通知許可を通す
5. `テスト通知を送る` で表示確認する
6. `Free Push / ntfy` に ntfy topic URL を入れる
7. 必要なら bearer token を入れる
8. `ntfyテスト送信` を押して、iPhoneのntfyアプリ側でも通知が届くか確認する

現状の通知対象:

- `Overview / Reflection / Dashboard` のWeb表示失敗
- 同じ失敗通知は30分抑制
- アプリ表示中でもバナー/リスト/サウンドを出す
- Command Center の通知履歴には、Web失敗/診断/Widget更新/通知テスト/ntfyテストが最大30件残ります
- `ntfy` は既存のBot/IBKR/日次通知と同じtopicを入れると、無料Pushの受信口として使えます

## 検証メモ

この repo では、native shell は既存Web画面を包むだけの薄いアプリとして扱います。  
ローカルでの基本確認は以下です。

- `project.pbxproj` の `plutil -lint`
- Asset Catalog の JSON 構文
