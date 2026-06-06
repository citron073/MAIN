# Ouroboros Quality Gate

このファイルは、Ouroboros用の軽量QAゲートです。
実装前の契約、shadow昇格条件、Widget/UI評価、LLM/日次反省の評価を1つの物差しにまとめます。

## 使い方

- `docs/ai_harness/WORKFLOW.md` と `docs/ai_harness/work_items.json` で、作業をセッションではなくワークアイテムとして管理する。
- `python3 tools/harness_work_items.py --show-items` で、着手可能なREADY作業と依存関係を確認する。
- 実装前に `docs/ai_harness/current_spec.md` とこのファイルを読む。
- `current_spec.md` の `Pre-Implementation Contract` に、今回どのゲートを通すかを書く。
- 実装後は `Review Checklist` を見て、該当項目だけ確認する。
- 判断に迷う場合は、main実弾ではなく shadow / observe / report-only に落とす。

## 0. 共通ゲート

すべての変更で守ること。

- 既存の `result` 意味、CSV列、daily report / audit の集計定義を壊さない。
- 秘密情報、トークン、APIキーをログ、通知、差分、最終回答へ出さない。
- 仕様外の大きなリファクタを混ぜない。
- main実弾挙動を変える場合は、先に shadow / observe / report-only で検証する。
- 欠損値、古いログ、0件ログでも落ちない。
- `./scripts/validate.sh fast` を最低ラインにする。
- trading / widget / notifier / reflection へ触れたら `./scripts/validate.sh trade` を通す。

## 1. 実装前契約

`current_spec.md` に最低限これを書く。

- `Work Item`: 対応する `docs/ai_harness/work_items.json` のID。無い場合は `ad-hoc` と理由。
- `Goal`: 今回やることを1つに絞る。
- `Allowed Files`: 編集してよいファイル。
- `Runtime Impact`: local-only / widget-only / shadow-only / report-only / VM deploy / main-live のどれか。
- `Data Contract`: 追加するJSONキー、noteキー、CSV利用、既存resultへの影響。
- `Safety Gate`: observe開始、shadow開始、PAPER昇格、main昇格、UIのみ、LLMのみのどれか。
- `Validation`: `fast` だけで足りるか、`trade` まで必要か。
- `Rollback`: 問題が出たら戻す設定、止めるサービス、無効化フラグ。

## 2. Shadow / Observe 昇格条件

新しい売買ロジックは原則この順で進める。

1. `observe-only`: エントリーせず、候補と理由だけ記録する。
2. `shadow-paper`: mainとは独立したPAPERでexitまで見る。
3. `paper-canary`: 条件を絞ってPAPERを少量運用する。
4. `main-canary`: 明示確認後、最小ロット/最小時間帯で実弾CANARYにする。

昇格前に見る条件。

- サンプル日数: 最低3営業日。強い偏りがある場合は延長。
- サンプル数: rank Aなど主要条件が少なすぎる場合は昇格しない。
- 期待値: pnlだけでなく、TP/SL/timeout/no_followの内訳を見る。
- 安全性: SL距離、risk stop、streak stop、drift gateの優先順位が崩れていない。
- 再現性: 良い日だけでなく、悪い日にも破綻していない。
- mainとの差分: shadowが良くても、mainに移す時の約定、spread、時間帯差を明記する。

昇格禁止の例。

- 1日だけ良かった。
- Aランクが数件しかない。
- `PAPER_EXIT_SL` を別名で隠している。
- TP/SLより先に便利exitが走って、損失判定を消している。
- 既存ログ/レポートが読めなくなる。

## 3. Widget / UI 評価基準

Widgetは「見た目」より「一目で運用判断できること」を優先する。

確認するサイズ。

- small: 最重要ステータスだけ。見切れたら情報を削る。
- medium: 目標/損益、稼働、drift、最新警告を横並びで読みやすくする。
- large: 日次、週間、shadow、反省の詳細を出してよい。

合格条件。

- iPhone実機で上下左右が見切れない。
- 日本語ラベルが短い。
- 右上や下部に無駄な空白がある場合は、情報カードか余白調整に使う。
- 重要度順が明確。警告、稼働状態、日次目標、残りサンプルを優先する。
- 取得失敗時も `通信NG` など短く出て、真っ白にならない。
- JSON payloadの欠損や古いサーバーでも壊れない。

避けること。

- 文字数を増やして全部表示しようとする。
- 1サイズだけに最適化して他サイズを崩す。
- 色だけで状態を伝える。
- 実データがない値を推測で表示する。

## 4. LLM / 日次反省 評価基準

LLMは「売買判断の主役」ではなく、振り返り、分類、説明、候補提案の補助として使う。

合格条件。

- LLMが落ちてもルールベースの反省レポートが出る。
- LLM出力は設定変更の候補に留め、main実弾設定を自動変更しない。
- 1日の目標、pnl、勝率、exit理由、shadow差分を入力に含める。
- `勝因/敗因/翌日の推奨設定/注意点` を短く構造化する。
- 出力に秘密情報、APIキー、トークンを含めない。
- 同じ日の反省が二重送信されない。
- 稼働終了時刻を見て、終了後に送れる。

強化してよい領域。

- 反省メモの分類: trend / htf / exit / filter / drift / execution。
- 週間まとめへの集約。
- shadowで良かった変更候補の抽出。
- Widget向けの短い要約生成。
- LLM不在時のルールベースfallback強化。

禁止すること。

- LLM単独で `CONTROL.csv` のmain実弾値を変更する。
- 損失やSLを「ノイズ」として除外する。
- 失敗ログを要約時に捨てる。
- VMや秘密情報へ無確認でアクセスする。

## 5. Review Checklist

実装後に該当するものだけ確認する。

- `Spec`: `current_spec.md` は `Status: READY` だったか。
- `Work Item`: `harness_work_items.py` の台帳チェックは通ったか。
- `Scope`: 変更は契約したファイルに収まっているか。
- `Safety`: main実弾挙動が変わるなら shadow / observe 検証を通したか。
- `Logs`: 既存のresult、CSV列、note形式、daily_report集計が壊れていないか。
- `Docs`: 売買ロジック、noteキー、stateキー、runner間隔を変えた場合、`docs/OUROBOROS_TRADING_SPEC_TABLE.md` / `HANDOVER.*` / `COMMANDS_QUICK.md` を更新したか。
- `Widget`: small / medium / large の欠損・見切れを想定したか。
- `LLM`: LLMなしでも動くfallbackがあるか。
- `Validation`: `fast` または `trade` を通したか。
- `Deploy`: VM反映が必要なら、反映ファイル、再起動サービス、確認結果を書けるか。
