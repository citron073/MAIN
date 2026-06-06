# Ouroboros Widget Guide

このファイルは、ダッシュボード本体とは別に「軽く現況だけ見る」ための導線です。
いまは `Mac常駐` と `Ubuntu / VM常駐` の両方に対応しています。

## 0. 今の状態
Mac常駐でできること:

- Mac が起動していてログイン中なら、widget 用サーバーは自動で動く
- iPhone のウィジェットは、そのサーバーを見に行って表示を更新する
- 毎回ターミナルで起動コマンドを打つ必要はない

Mac常駐の制約:

- Mac を閉じてスリープすると止まる
- 外出先のモバイル回線や別Wi-Fiからは、そのままでは見えない

VM常駐でできること:

- Mac を閉じていても VM が動いていれば見られる
- systemd で自動起動・再起動される
- 公開IPまたは別の公開手段を使えば、外出先からも参照できる

## 1. 何ができるか
- CLIで現在状態を1コマンド表示
- 軽量Web画面を起動して、Mac / iPhone のブラウザで閲覧
- Macは SwiftBar でメニューバー常駐
- iPhoneは Scriptable でホーム画面ウィジェット化

元データは `MAIN/tools/widget_status.py` が `state.json` / `CONTROL.csv` / `.run_lock` を読んで生成します。

## 2. 最短確認
Mac ローカルで動かす場合:
```bash
cd ~/trading_bot/trading_bot/MAIN
python3 tools/widget_status.py --print-text
```

Ubuntu / VM で動かす場合:
```bash
cd ~/trading_bot/trading_bot/MAIN
pwd
python3 tools/widget_status.py --print-text
```

もし `tools/widget_status.py: No such file` なら、その VM にはまだ widget ファイルが未配布です。

## 3. Web版を起動
同じWi-Fi内の iPhone / Mac から見る場合:

```bash
cd ~/trading_bot/trading_bot/MAIN
WIDGET_STATUS_HOST=0.0.0.0 ./tools/start_widget_status_server.sh
```

VM に widget ファイルを配る場合は、Mac 側から:

```bash
cd /Users/tani/trading_bot/trading_bot/MAIN
VM_HOST=<YOUR_VM_IP>
VM_KEY=/Users/tani/Downloads/ssh-key-2026-03-04-4.key
./tools/deploy_vm_components.sh --host "$VM_HOST" --key "$VM_KEY" --with-widget-status
```

VM常駐にする場合は、`/etc/ouroboros/secrets.env` に token を入れておくと安全です。

```bash
echo "WIDGET_STATUS_TOKEN='change-this-token'" | sudo tee -a /etc/ouroboros/secrets.env
sudo chmod 600 /etc/ouroboros/secrets.env
```

`deploy_vm_components.sh --with-widget-status` は、いまはファイル転送だけでなく
`ouroboros-widget-status.service` の反映・起動まで行います。

VM 側の確認:
```bash
cd ~/trading_bot/trading_bot/MAIN
python3 tools/widget_status.py --print-text
sudo systemctl status ouroboros-widget-status.service --no-pager -l
sudo journalctl -u ouroboros-widget-status.service -n 80 --no-pager
curl "http://127.0.0.1:8787/widget-status.json?token=change-this-token"
```

推奨:
- LANだけなら `WIDGET_STATUS_TOKEN` は任意
- 外部公開や ngrok 併用や VM 直公開なら `WIDGET_STATUS_TOKEN` を必ず設定

例:
```bash
cd ~/trading_bot/trading_bot/MAIN
export WIDGET_STATUS_TOKEN='change-this-token'
WIDGET_STATUS_HOST=0.0.0.0 ./tools/start_widget_status_server.sh
```

常駐化する場合:
```bash
cd ~/trading_bot/trading_bot/MAIN
./tools/install_widget_status_launchagent.sh \
  --host 0.0.0.0 \
  --port 8787 \
  --token 'change-this-token' \
  --replace-running
```

停止/解除:
```bash
cd ~/trading_bot/trading_bot/MAIN
./tools/uninstall_widget_status_launchagent.sh
```

今はすでに常駐化済みなら、上の install を毎回打つ必要はありません。

VM を systemd 常駐化する場合:
```bash
cd ~/trading_bot/trading_bot/MAIN
./tools/install_systemd_services.sh --with-widget-status
sudo systemctl restart ouroboros-widget-status.service
```

開くURL:
- Macローカル: `http://127.0.0.1:8787/`
- ZIP React完全移植導線: `http://127.0.0.1:8787/widget-react/index.html`
- ZIP React通常Overview固定: `http://127.0.0.1:8787/widget-react/index.html?scene=overview`
- ZIP React通常Overviewネイティブ埋め込み: `http://127.0.0.1:8787/widget-react/index.html?scene=overview&native=1`
- ZIP React反省固定: `http://127.0.0.1:8787/widget-react/index.html?scene=reflection`
- ZIP React反省ネイティブ埋め込み: `http://127.0.0.1:8787/widget-react/index.html?scene=reflection&native=1`
- ZIP Reactホーム固定: `http://127.0.0.1:8787/widget-react/index.html?scene=home`
- ZIP Reactロック固定: `http://127.0.0.1:8787/widget-react/index.html?scene=lock`
- ZIP Reactスタンド固定: `http://127.0.0.1:8787/widget-react/index.html?scene=standby`
- ホーム画面風アプリ導線: `http://127.0.0.1:8787/widget-home`
- PWAアプリ導線: `http://127.0.0.1:8787/widget-app`
- iPhone同一Wi-Fi: `http://<MacのLAN IP>:8787/`
- VMローカル確認: `http://127.0.0.1:8787/`
- VM公開IP: `http://<VMのPublic IP>:8787/`
- トークン付き: `http://<host>:8787/?token=<YOUR_TOKEN>`
- トークン付きZIP React完全移植導線: `http://<host>:8787/widget-react/index.html?token=<YOUR_TOKEN>`
- トークン付きZIP React通常Overview固定: `http://<host>:8787/widget-react/index.html?token=<YOUR_TOKEN>&scene=overview`
- トークン付きZIP React通常Overviewネイティブ埋め込み: `http://<host>:8787/widget-react/index.html?token=<YOUR_TOKEN>&scene=overview&native=1`
- トークン付きZIP React反省固定: `http://<host>:8787/widget-react/index.html?token=<YOUR_TOKEN>&scene=reflection`
- トークン付きZIP React反省ネイティブ埋め込み: `http://<host>:8787/widget-react/index.html?token=<YOUR_TOKEN>&scene=reflection&native=1`
- トークン付きZIP Reactホーム固定: `http://<host>:8787/widget-react/index.html?token=<YOUR_TOKEN>&scene=home`
- トークン付きZIP Reactロック固定: `http://<host>:8787/widget-react/index.html?token=<YOUR_TOKEN>&scene=lock`
- トークン付きZIP Reactスタンド固定: `http://<host>:8787/widget-react/index.html?token=<YOUR_TOKEN>&scene=standby`
- トークン付きホーム画面風アプリ: `http://<host>:8787/widget-home?token=<YOUR_TOKEN>`
- トークン付きPWA導線: `http://<host>:8787/widget-app?token=<YOUR_TOKEN>`

ホーム画面に追加したい場合:
1. iPhoneで URL を開く
2. 共有
3. `ホーム画面に追加`

補足:
- `/widget-react/index.html` は添付された `ウィジェット.zip` のReactファイル一式をそのまま配信する完全移植導線です
- `/widget-react/index.html` は `portfolio-widget/ouroboros-live.jsx` が `/widget-status.json` を読み、ZIPの見た目へ実データを流し込みます
- `/widget-react/index.html?scene=overview|reflection|home|lock|standby` で、通常Overview / 反省 / ホーム画面 / ロック画面 / スタンド画面を固定表示できます
- `native=1` は native app 埋め込み専用です。確認用ヘッダー、scene切替、iPhoneモック枠を出さず中身だけ表示します
- `scene=lock` はロック画面ウィジェットに加えて、ホーム画面用ウィジェットのプレビューも横に出します
- `scene=lock` と `scene=standby` はnative appの通常タブには出さず、将来のロック/横置き表示用として残しています
- `/widget-home` は添付された `ウィジェット.zip` の iPhone ホーム画面風UIを元にした新しい外出先向けアプリ導線です
- `/widget-home` も token つきで使い、既存の `/widget-status.json` を読むだけなので売買ロジックは持ちません
- `/widget-app` は `manifest` と `service worker` を使う軽量PWA導線です
- `/widget-app-icon.svg` を持ち、ホーム画面追加時の見た目を軽くアプリ寄りにしている
- 既存の `/widget-status.json` や Scriptable ウィジェットはそのまま使えます
- `Overview / Reflection / Dashboard` の小さいナビを持ち、PWAから主要画面へ移動できます
- `widget-app` では下部固定タブ風ナビを出し、iPhoneで片手操作しやすくしています
- オフライン時は `service worker` が最後に取得できたJSONを優先し、無ければ簡易 `offline` 状態を返して真っ白を避けます
- `Reflection Snapshot` カードで、その日の反省要点を Overview から直接見られます

native app として使いたい場合:
- `MAIN/widget_native_ios/OuroborosWidgetNative/OuroborosWidgetNative.xcodeproj`
- SwiftUI + WKWebView の薄い shell です
- `Settings` タブで Host と token をローカル保存し、`Overview / Reflection / Dashboard` を native tab で開きます
- `Overview` はZIP React完全移植版の `/widget-react/index.html` を開きます
- native app の `Overview / Reflection` はそれぞれ `scene=overview&native=1 / scene=reflection&native=1` を固定して開きます
- `Overview` のZIP React版は Balance / Daily Goal / Weekly / Ops を実ステータスから生成します
- `Overview` には `Account Stack` を表示します。`Account Stack` は口座別の残高/Cash/当日P&L/Week%を細かく確認できます
- `OuroborosWidgetNativeWidget` は WidgetKit Extension です。ホーム画面 `Small / Medium`、ロック画面 `Circular / Rectangular / Inline` に対応します
- WidgetKit側は App Group `group.com.ouroboros.widgetnative` で Host/token を共有し、`/widget-status.json` を読みます
- WidgetKit側はサイズに応じて表示密度を変えます。`Small` は黒い口座カード風、`Medium` は詳細、ロック画面系は円形ドーナツ/横長ピル/インラインの凝縮表示です
- 配置済みWidgetを長押しして `ウィジェットを編集` を開くと、表示内容を `自動 / 口座 / シャドウ / 日次 / 週次` から選べます
- `自動` はホーム画面で口座カード、ロック画面で口座/シャドウ状態を凝縮表示します
- ホーム画面Widgetは標準マージンを無効化し、添付デザインの `OB / Ouroboros / Balance / Donut / Cash-Health-Energy` に寄せています
- native app の `Settings` には Native通知設定があります。アプリ表示中のWeb表示失敗を30分抑制でローカル通知します
- native app の `Command` は `/widget-status.json` を直接読む管制室です。口座/日次/週次/Shadow/診断/通知履歴/Widgetプリセットを1画面で確認できます
- native app の `Settings` で `Command CenterをFace IDで保護` をONにすると、口座系の管制画面をFace ID/パスコードで保護できます
- `Command` の `診断する` は Widget JSON / Dashboard / Runner / Trade / Shadow を読み取り専用で確認し、結果を通知履歴に残します
- `Command` の `Widget更新` は WidgetKit timeline を再読み込みします。表示内容の変更は配置済みWidgetを長押しして `ウィジェットを編集` から選びます
- `Command` の `Live Activity` は、ロック画面/Dynamic Island に稼働状態を出すネイティブ機能です。`開始 / 更新 / 終了` は手動操作で、APNsなしの無料運用として使えます
- Live Activity には `Trade / Runner / Balance / Daily / Weekly / Shadow` を凝縮表示します。完全自動のバックグラウンド更新はAPNs/サーバー追加後の扱いです
- 無料の外部Pushは `ntfy` を使います。Settings の `Free Push / ntfy` に既存topicを入れると、Bot/IBKR/日次通知と同じ無料Push経路を確認できます
- 独自の完全バックグラウンドPushはAPNs/サーバー追加後の扱いです
- 売買ロジックや token 保護は既存の Web 側をそのまま使います

## 4. Macメニューバー表示
SwiftBar を使う場合はサンプルをプラグインディレクトリへコピーまたは symlink してください。

対象:
- `MAIN/widget/swiftbar/ouroboros.1m.sh`

必要なら `OUROBOROS_MAIN_DIR` を環境変数で上書きできます。

## 5. iPhoneウィジェット
Scriptable を使う場合は、まず `MAIN/widget/scriptable/OuroborosWidget.local.js` を使うのが最短です。

対象:
- `MAIN/widget/scriptable/OuroborosWidget.js`
- `MAIN/widget/scriptable/OuroborosWidget.local.js`

Scriptable 側で作成後:
1. スクリプト保存
2. ホーム画面でウィジェット追加
3. Scriptable を選択
4. このスクリプトを割り当て

推奨手順:
1. iPhone に `Scriptable` を入れる
2. いちばん楽なのは、次の 1 コマンドで export と iCloud 配置をまとめてやること
```bash
cd ~/trading_bot/trading_bot/MAIN
./tools/publish_scriptable_widget.sh
```
3. 手動で分ける場合は、まず転送用ファイルを生成する
```bash
cd ~/trading_bot/trading_bot/MAIN
./tools/export_scriptable_widget.sh
```
4. そのあと Scriptable の iCloud フォルダへ直接コピーする
```bash
cd ~/trading_bot/trading_bot/MAIN
./tools/copy_widget_to_scriptable_icloud.sh
```
5. iPhone の Scriptable を開いて iCloud 同期を待つ
6. スクリプト一覧に `OuroborosWidget.local` が出たら実行してプレビュー確認
7. ホーム画面で Scriptable ウィジェットを追加
8. そのウィジェットに今のスクリプトを割り当てる

補足:
- Apple Notes はコード転送で改行や書式が崩れることがあるので非推奨です
- `AirDrop で .js を送ってそのままコピペ` は、iPhone 側で選択や貼り付けが不安定なことがあります
- AirDrop を使うなら `MAIN/widget/scriptable/export/OuroborosWidget.local.transfer.txt` を送って、`ファイル` か `メモ` で開いて全選択コピーする方が安全です
- いちばん安定するのは、AirDrop ではなく Scriptable の iCloud フォルダへ直接置く方法です
- `.local` 名で届かない時は、同ファイル内の `192.168.3.52` 側がフォールバックします
- ウィジェットをタップすると簡易Web画面へ飛びます
- `大` サイズのウィジェットをタップすると、終業反省がある日は `/daily-reflection` を開きます
- 将来 IP が変わっても、`taninoMacBook-Air.local` が通ればそのまま動きます
- 外出先用に切り替えるときは、Scriptable の `Parameter` で baseUrls を上書きします

サイズごとの表示:
- `小`: `残り件数` を主役表示。`日次目標 / 残高 / 鮮度 or 直近トレード / 停止/復帰`
- `中`: 標準表示。`取引 / bot / ドリフト / 日次目標 / 残高` と、要約行に `鮮度 / 直近トレード`
- `大`: 中サイズに加えて、`鮮度 / 直近 / 今週累計 / 直近確定数 / 通常条件 / カナリア条件 / 影bot / 反省導線`

AirDrop を使う場合の最短:
1. `./tools/export_scriptable_widget.sh` を実行する
2. `MAIN/widget/scriptable/export/OuroborosWidget.local.transfer.txt` を iPhone に AirDrop する
3. iPhone の `ファイル` で開く
4. 全選択してコピーする
5. Scriptable で新規スクリプトを作り、全文貼り付けして保存する

iCloud 直コピーの方が向いているケース:
- 何度も更新する
- コピペ事故を減らしたい
- iPhone 側でコード選択に時間をかけたくない

## 6. API / 出力
- `/widget-status.json`
- `/widget-status.txt`
- `/` または `/widget`
- `/widget-home`
- `/widget-home-manifest.json`
- `/widget-home-sw.js`
- `/widget-app`
- `/widget-app-manifest.json`
- `/widget-app-sw.js`
- `/widget-app-icon.svg`
- `/daily-reflection`
- `/daily-reflection.json`

CLIでファイル保存も可能です:
```bash
python3 tools/widget_status.py --json-out /tmp/ouroboros_widget.json --text-out /tmp/ouroboros_widget.txt
```

補足:
- `今週累計` は `state.json` の `_weekly_auto_feedback.shadow_weekly_review` があれば、`保留 / entry品質不足` のような週次ヒントも detail 行へ表示します。

鮮度しきい値を変えたい場合は `MAIN/.streamlit/secrets.toml` の `[dashboard_security]` に追加:
```toml
widget_freshness_warn_sec = 300
widget_freshness_alert_sec = 900
```

## 7. 注意
- 本体ダッシュボードとは別系統です。認証付き dashboard の代替ではなく、簡易監視面です。
- `state.json` や `CONTROL.csv` が古いと、表示も古くなります。
- `logs/` が無い環境では損益集計は出さず、状態中心で表示します。
- LaunchAgent 化した後は、手動で `start_widget_status_server.sh` を二重起動しないでください。ポート競合します。

## 8. 外から見たい場合
Mac常駐のままでは、外出先からは見られません。

外から見たい場合の候補:

- `ngrok` で widget 用サーバーを外部公開する
- `Tailscale` で iPhone と Mac を同じ仮想ネットワークに入れる
- Ubuntu / Cloud 側へ widget status を置いて、インターネット越しに見せる

PC を閉じても見たいなら、`Ubuntu / Cloud 側へ widget status を置く` のが本命です。
この場合も token は必須です。

補足:
- VM 直IPで見せるなら、クラウド側で `TCP 8787` の ingress を開ける必要があります
- もし 8787 を開けたくないなら、VM 上で別の公開手段を使ってください

## 9. Tailscale で外から見る
無料で長く使うなら、外出先対応は `Tailscale` が一番現実的です。

前提:
- Mac に Tailscale を入れる
- iPhone に Tailscale を入れる
- 同じアカウントで両方サインインする

Mac 側:
1. Tailscale をインストール
2. サインイン
3. VPN / system extension の許可が出たら許可

iPhone 側:
1. Tailscale アプリをインストール
2. 同じ Tailnet に入る
3. 必要なら次のコマンドで candidate URL を確認する

```bash
cd ~/trading_bot/trading_bot/MAIN
python3 tools/print_widget_tailscale_info.py --token 'change-this-token'
```

このコマンドは token を自動表示しません。自分で token を渡した時だけ、次の候補をまとめて出します。

- widget base URLs
- widget app URLs
- dashboard URLs

ホーム画面風アプリとして使う時は、`widget app URLs` に出る host を使い、入口は `/widget-home` 側を優先します。

VM / Tailscale の固定導線:

- Widget React: `http://100.66.216.5:8787/widget-react/index.html?token=<YOUR_TOKEN>`
- Widget React Home: `http://100.66.216.5:8787/widget-react/index.html?token=<YOUR_TOKEN>&scene=home`
- Widget React Lock: `http://100.66.216.5:8787/widget-react/index.html?token=<YOUR_TOKEN>&scene=lock`
- Widget React StandBy: `http://100.66.216.5:8787/widget-react/index.html?token=<YOUR_TOKEN>&scene=standby`
- Widget home: `http://100.66.216.5:8787/widget-home?token=<YOUR_TOKEN>`
- Widget app: `http://100.66.216.5:8787/widget-app?token=<YOUR_TOKEN>`
- Widget JSON: `http://100.66.216.5:8787/widget-status.json?token=<YOUR_TOKEN>`
- Unified Dashboard: `http://100.66.216.5:8793/tools/unified_dashboard.html`
2. 同じアカウントでサインイン
3. VPN の許可を出す

Mac で接続先候補を確認:
```bash
cd ~/trading_bot/trading_bot/MAIN
python3 tools/print_widget_tailscale_info.py --token 'change-this-token'
```

このコマンドは:
- Tailscale の DNS 名
- Tailscale IP
- Scriptable の `Parameter` に貼る JSON

をまとめて出します。

Scriptable 側では:
1. 既存の `OuroborosWidget.local` を使ってよい
2. iPhone のウィジェット編集画面で `Parameter` に、上の JSON をそのまま貼る

補足:
- `Parameter` を入れると、script 内の `192.168.x.x` や `.local` より優先されます
- つまり外出先用に script を作り直さなくても使えます
- Mac 側の widget server はすでに常駐化済みなので、Tailscale がつながればそのまま見える想定です

## 10. VM常駐で外から見る
VM 側に移した場合、Scriptable の `Parameter` は次の形です。

```json
{"baseUrls":["http://<VM_PUBLIC_IP>:8787"],"token":"change-this-token"}
```

流れ:
1. VM に `--with-widget-status` で配布する
2. `/etc/ouroboros/secrets.env` に `WIDGET_STATUS_TOKEN` を入れる
3. `sudo systemctl restart ouroboros-widget-status.service`
4. Mac または iPhone から `http://<VM_PUBLIC_IP>:8787/widget-status.json?token=<TOKEN>` を開いて確認
5. Scriptable ウィジェットの `Parameter` を上の JSON に置き換える
