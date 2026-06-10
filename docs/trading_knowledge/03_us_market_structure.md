# 03. 米株デイトレード特有の市場構造 — 知識ベース

> 対象: 米国株のデイトレード（IBKR bot 含む / 1〜5分足）
> 方針: 権威ソース2つ以上で裏取り、規則・数値は原典引用。時刻は ET と JST を併記。末尾に参考URL一覧。
> 作成: 2026-06-11 JST
> 注意: 後述「PDTルール」は **2026年6月4日に大幅改定**（$25,000 撤廃）。古い情報が大量に残っているため原典で確認すること。

---

## 結論先出し（このドキュメントの要旨）

1. **エッジは時間帯に偏在する。** 寄り後の 9:30–11:30 ET（=22:30–00:30 JST 冬時間）が最も出来高・トレンド・値動きが揃う。逆に 11:30–13:30 ET（ランチ）は出来高が薄く方向感が消え、騙しが増える「最悪の時間帯」とされる（Trade That Swing / QuantPedia ほか）。
2. **米株の市場構造は「ボラ抑制の仕組み」が二層ある。** 個別銘柄は LULD（Limit Up-Limit Down、5分ポーズ）、市場全体は Market-Wide Circuit Breaker（7%/13%/20%）。デイトレ bot はこの「ホルト中は約定不能・解除後にギャップ」を必ず想定する必要がある。
3. **PDTルールは2026/6/4に撤廃された。** $25,000 最低資本・トレード数カウントは廃止され、「日中の証拠金不足（intraday margin deficit）をリアルタイム監視」する方式へ移行（FINRA 原典）。ただし維持証拠金 25% 等は残る。
4. **このbotへの示唆**: 9:45 開始は妥当だが「寄り直後の高ボラ・ホルト多発帯（9:30–9:45）を意図的に外している」と再解釈できる。一方、現状 9:45–15:50 を通しで回すとランチ薄商い帯（11:30–13:30 ET）も含むため、ここを除外/縮小するだけでノイズ取引を減らせる。深夜運用（22:30–05:00 JST）ゆえホルト・ギャップを人が見られない前提のリスク設計が必須。

---

## 1. 取引時間（セッション構造）

### 1-1. 3つのセッション（Eastern Time / 原典: NYSE・Nasdaq）

| セッション | ET | JST(冬/EST, UTC-5) | JST(夏/EDT, UTC-4) | 特性 |
|-----------|-----|----------|----------|------|
| **プレマーケット** | 4:00–9:30（Nasdaq）/ NYSE Arca 4:00、他NYSE市場 7:00 | 18:00–23:30 | 17:00–22:30 | 薄商い・スプレッド広・決算/材料に反応。流動性低くスリッページ大 |
| **通常(RTH, Core)** | **9:30–16:00** | **23:30–06:00** | **22:30–05:00** | 本番。出来高・流動性最大。LULD はこの時間のみ適用 |
| **アフターアワーズ** | 16:00–20:00 | 06:00–10:00 | 05:00–09:00 | 決算発表が集中。薄商い・急変動 |

- NYSE 公式: Core Trading Session = **9:30 a.m. to 4:00 p.m. ET**、Early Trading は市場により 4:00 または 7:00–9:30、Late Trading 4:00–8:00 p.m.（NYSE Hours & Calendars）。
- Nasdaq: プレマーケット 4:00–9:30、アフター 4:00–8:00 p.m.（Nasdaq / Fidelity）。
- **重要**: 米国は夏時間（DST）を採用。3月第2日曜〜11月第1日曜が EDT(UTC-4)。**日本は夏時間なしのため、JST換算が年2回ズレる**。RTH 開始は冬 23:30 JST / 夏 22:30 JST。bot のスケジュールは ET 基準で持ち、JST は表示用にする（DSTズレ事故の定番）。

### 1-2. 各セッションの実務特性（複数ソースの共通見解）

- **プレ/アフター = 高ボラ・低流動性**。「Extended Markets carry risks. The volatility tends to be much higher, and there is less liquidity」（Fidelity / TD）。スプレッドが広く、成行は厳禁（指値必須）。
- **LULD はプレ/アフターでは適用されない**（RTH 9:30–16:00 のみ）。つまり時間外はブレーキなしで飛ぶ。
- 決算・経済指標は時間外に出るため、**ポジションを持ち越すと窓（ギャップ）で寄る**。

---

## 2. 寄り付きの値動き・ギャップ・ギャップフィル

### 2-1. オープニングレンジブレイクアウト（ORB）

- **定義**: 「the day's first range（始値後の最初の一定時間に作った高値・安値の箱）を引き、そのブレイクを取る」戦略。窓は **5分 / 15分 / 30分** が一般的（ForexTester / BuildAlpha / LiteFinance）。
- 使い方:
  - 最初のN分の **高値・安値（オープニングレンジ）** を箱として確定。
  - 価格が箱の上抜け（終値ベース）= 強気ブレイク、下抜け = 弱気ブレイク。
  - **リスクは箱の幅で定義**（損切りを反対端に置ける）→ R:R 設計がしやすいのが利点。
- 窓の選び方（一般則）:
  - 5分 = シグナル多・ノイズ多（速い）
  - **15分 = 株で最も一般的**。「reduces some of the initial trading noise」（ForexTester）
  - 30分 = シグナル少・クリーンな動き（選別）
- **勝ちやすい条件**: 「performs best on days when the market opens with clear momentum or strong global cues. Gap openings, major economic events, or strong sector moves」（ForexTester）。= **ギャップ・指標・セクター連動がある日**。出来高を伴うブレイクが信頼度高。
- **時間帯**: 最もボラが高いのは「the first hour after the market opens」（寄り後1時間 = 9:30–10:30 ET / 冬 23:30–00:30 JST）。

### 2-2. ギャップ（gap up / gap down）

- **ギャップアップ** = 前日終値より高く寄る、**ギャップダウン** = 低く寄る。要因は決算・材料・指標・地合い。
- **VWAP との関係（実務の定番フィルタ）**:
  - 「gaps up and stays above VWAP shows strong buying pressure（窓開け後 VWAP 上を維持 = 強い）」
  - 「gaps down and struggles to get above VWAP shows strong selling（VWAP を超えられない = 弱い継続）」（gap+VWAP ソース）。
- **ギャップフィル（窓埋め）の考え方**:
  - 「Not all gaps get filled（全ての窓が埋まるわけではない）」。**common gap / exhaustion gap は埋まりやすく、breakaway gap（出来高を伴うブレイク窓）は埋まりにくい**（QuantifiedStrategies / StockCharts ChartSchool）。
  - 「Small gaps are more likely to get filled（小さい窓ほど埋まりやすい）」。
  - 「When VIX is above 25, intraday mean-reversion dominates and gap fills become the higher-probability play（高ボラ時は窓埋めが優勢）」。
  - **出来高が最重要**: 「a breakaway gap needs very high volume to be reliable」。出来高薄い窓開けは騙しになりやすい。

### 2-3. デイトレでの寄り運用ルール（合成）

1. 最初の数分は **値動きが激しく LULD ホルトも出やすい** → ORB の箱が固まるまで（最低5–15分）はエントリーを待つのが定石。
2. **VWAP を超えているか/下回っているか**で窓のフォロー方向を判断。
3. 窓埋め狙い（リバージョン）と窓フォロー（ブレイク）は**真逆の賭け**。日のレジーム（VIX・出来高）で使い分ける。

---

## 3. PDTルール（Pattern Day Trader）— ★2026/6/4 改定済み

> **最重要の更新**。原典: FINRA Regulatory Notice 26-10 / FINRA Investor Insight「Intraday Margin Requirements」/ SEC SR-FINRA-2025-017。

### 3-1. 旧ルール（2001〜2026/6/3、参考・歴史）

- **パターンデイトレーダー** = マージン口座で「**5営業日内に4回以上のデイトレ**」を行い、かつそれが全取引の **6% 超** だった顧客の FINRA 区分（Wikipedia / FINRA 旧規則）。
- 該当者は **最低 $25,000 の口座資本**を、デイトレ開始**前に**維持する義務があった。
- 違反すると 90日のデイトレ制限等。

### 3-2. 新ルール（2026/6/4 施行）★現行

- 原典の言葉: **「There's no $25,000 minimum equity requirement for day trading. There's no 'pattern day trader' designation based on counting trades.」**（FINRA）。
- 代わりに **「intraday margin deficit（日中証拠金不足）」をリアルタイム監視**する方式へ。日中、保有ポジションに対し口座資本が不足した瞬間を「不足」とみなし、**速やかに解消**することを求める。
- **維持証拠金**: 「at least 25 percent of the current market value of long margin-eligible securities throughout the entire trading day（ロングの時価の25%以上を日中ずっと維持）」。
- **ペナルティ**: 日中証拠金不足を繰り返し速やかに解消しないと、**最大90日の口座制限**。
- **施行日 2026年6月4日**、必要な会員業者は **2027年10月20日まで** 段階導入可（FINRA / SEC）。

### 3-3. このbotへの影響

- **資本要件の壁が下がった**: 旧$25,000 縛りは消えたが、**IBKR が自社方針として独自の最低資本・マージン監視を課す可能性は残る**（FINRA は下限、ブローカーは上乗せ可）。実弾投入前に **IBKR の最新ハウスルール**を必ず確認（領域1=資金。LIVE切替はたにさん承認）。
- **日中証拠金不足の即時解消**が新たな失格条件。bot がポジションを持ったまま価格急変→証拠金割れ、を放置すると制限対象。**深夜無人運用では特に危険**（後述§9）。

---

## 4. サーキットブレーカー / LULD / 個別ホルト

### 4-1. 市場全体（Market-Wide Circuit Breaker, MWCB）

> 原典: SEC Investor.gov「Stock Market Circuit Breakers」。基準指数 = **S&P 500**。閾値は前日終値から毎日再計算。

| レベル | 下落率 | 発動時の挙動 |
|-------|-------|------------|
| **Level 1** | **-7%** | **3:25 p.m. ET 前**なら市場全体を **15分** 停止。3:25以降は停止しない |
| **Level 2** | **-13%** | 同上（3:25前は15分停止 / 3:25以降は停止しない） |
| **Level 3** | **-20%** | **時刻問わずその日の取引終了まで全停止** |

- 「triggered at three circuit breaker thresholds—7% (Level 1), 13% (Level 2), and 20% (Level 3)」「calculated daily based on the prior day's closing price of the S&P 500 Index」（SEC）。
- 1日のうち各レベルは原則1回（Level 1/2 は1回ずつ）。

### 4-2. 個別銘柄: LULD（Limit Up-Limit Down）

> 原典: SEC Investor.gov / NYSE。RTH（9:30–16:00 ET）のみ適用。

- 目的: 個別銘柄の急変動抑制。**直近5分間の平均価格**を基準に上下のプライスバンドを設定。
- 「If the stock's price moves to the price band and does not move back within the price bands within **15 seconds**, trading in the stock will pause for **5 minutes**（バンド到達後15秒戻らなければ5分ポーズ）」（SEC）。
- バンド幅 = **5% / 10% / 20% / lesser of $0.15 or 75%**。銘柄価格と Tier 1（S&P500・Russell1000・主要ETF）/Tier 2 の区分で変わる（SEC）。
- **適用は 9:30–16:00 ET のみ**（プレ/アフターはLULDなし＝ブレーキなし）。

### 4-3. 個別ホルト（Trading Halt）

- 上記 LULD ポーズのほか、**ニュース保留(news pending)・規制(regulatory)ホルト**がある。決算・買収・SECの照会等で発生。
- ホルト中は**約定不能**。解除時は**板が薄く寄り直しでギャップ**。bot は「ホルト→解除直後の数分」を最も危険な約定帯として扱うべき。

---

## 5. 板情報（Level 2）・歩み値・流動性・スプレッド

### 5-1. 基礎用語

| 用語 | 意味 |
|------|------|
| **Level 1** | 最良買気配(Bid)・最良売気配(Ask)・直近約定のみ |
| **Level 2（板/Depth）** | 各価格帯の注文（指値）の厚みを表示。どこに大口の壁があるか可視化 |
| **Time & Sales（歩み値）** | 実際に約定したティックの連続。「成立した取引」=本物の需給。板（出ているだけの注文）より信頼度が高い |
| **Bid-Ask Spread** | Ask − Bid。流動性の代理指標。狭い=流動性高、広い=薄い |

- **板は「気配（出ているだけ）」、歩み値は「成立（実需）」**。板は引っ込む（spoofing 含む）ため、デイトレでは歩み値で実際の買い/売りの強さを確認するのが基本。
- **流動性 = 出来高 × スプレッドの狭さ**。出来高が大きく板が厚いほど、大口でも価格を動かさず約定でき、スリッページが小さい。

### 5-2. スプレッド/流動性とコスト

- スプレッドは**往復の実質コスト**。薄い銘柄・薄い時間帯（プレ/アフター/ランチ）では広がり、勝率以前にコストで負ける。
- デイトレは**狭スプレッド・高出来高銘柄**（大型株・主要ETF）に絞るのが鉄則。QQQ・SPY 等のメガETFはスプレッド最狭クラス。

---

## 6. 浮動株（float）・カタリスト主導・低浮動株の危険性

### 6-1. 用語

- **Float（浮動株）** = 市場で実際に売買できる株数（発行済 − 内部者・固定保有分）。
- **Catalyst（カタリスト）** = 値動きの引き金（決算・ガイダンス・FDA承認・M&A・指標・格付け）。

### 6-2. 低浮動株（low-float）の危険

- 浮動株が少ない銘柄は**少ない出来高で価格が暴れる**（薄い板）。カタリストで数十%動く反面、**スプレッドが広く・LULDホルト連発・スリッページ甚大**。
- デイトレの花形である一方、**bot の機械的執行とは相性が悪い**（約定不確実・ギャップ・ホルトで損切りが滑る）。
- → **無人/深夜運用 bot は低浮動株を避け、大型・高流動の名柄(QQQ/SPY等)に限定**するのが安全。

---

## 7. IBKR（Interactive Brokers）特有の注意点

> 原典: Interactive Brokers 公式（Order Types / Commissions / Market Data Pricing / SmartRouting）。

### 7-1. 注文・執行

- **SmartRouting**: 「searches for the best firm stock/option prices ... seeks to immediately execute electronically」。8つのダークプールを含めて最良執行を探す。
- 多彩な注文種別: Pegged-to-Midpoint / Pegged-to-Best / Relative(Pegged-to-Primary) / Pegged-to-Market、および **Adaptive algo**（SmartRouting + 優先度設定で速い最良約定を狙う）。
- デイトレでは **成行(MKT)はスリッページ大** → 指値(LMT)・stop-limit・Adaptive を使い分け。

### 7-2. 市場データ（重要な落とし穴）

- **リアルタイムデータは購読制**。「Accounts must generate at least **USD 30 in commissions per month** per user subscribed to market data（月$30以上の手数料を出さないとデータ料が請求される）」。
- 初期は「100 concurrent lines of real-time market data（最低100ライン保証）」。
- **paper/未入金だとリアルタイム板が無い/遅延の可能性** → bot が遅延データで判断すると、実価格と乖離した約定をする。**LIVE 前にデータ購読状態を必ず確認**。

### 7-3. 手数料（概念）

- **IBKR Lite**: 対象US株/ETF **$0**。
- **IBKR Pro Tiered**: 株 **$0.0005–0.0035/株**（出来高で逓減）+ 取引所手数料/リベートのパススルー。
- **IBKR Pro Fixed**: 株 **$0.005/株**。
- デイトレは回転数が多い → 1株あたりコスト × 往復 × 回数 が効く。**1株/QQQ のような小ロット高頻度は、最低手数料と片道コストでエッジが食われやすい**ことを試算で確認すべき。

---

## 8. デイトレに向く/避けるべき時間帯

> 原典: Trade That Swing / QuantPedia / QuantifiedStrategies / 各トレード教育。

| 時間帯(ET) | JST(夏/EDT) | JST(冬/EST) | 評価 | 内容 |
|-----------|------------|------------|------|------|
| 9:30–11:30 | 22:30–00:30 | 23:30–01:30 | **◎ 最良** | 高出来高・トレンド形成・最も信頼できる値動き。寄り後1時間が最ボラ |
| 11:30–13:30 | 00:30–02:30 | 01:30–03:30 | **× 最悪（ランチ）** | 出来高激減・アルゴ鈍化・チョップ。「the edge evaporates」。プロは手を止める時間 |
| 13:30–15:00 | 02:30–04:00 | 03:30–05:00 | △ | 徐々に出来高戻る。様子見〜小ロット |
| 15:00–16:00 | 04:00–05:00 | 05:00–06:00 | ○ Power Hour | 2番目に活発。ただし**反転が速い**。引け前のクローズ需給 |

- 「9:30 AM–11:30 AM ET ... best window for day trading, combining high volume, emerging trends」。
- 「midday lull (11:30 AM–1:30 PM) is generally the worst time ... Many professional day traders simply stop trading」「Volume drops significantly as institutional traders take lunch, algorithmic activity slows, price action becomes choppy」（Trade That Swing / QuantPedia の Lunch Effect）。

---

## 9. このbotへの紐付け（IBKR bot 専用セクション）

> 現状: QQQ中心+約40銘柄ユニバース、**9:45–15:50 ET**、1分足SMAクロス、VIX≥30ブロック、未入金(paper)。
> 運用制約: US場 = **日本深夜（冬 23:30–06:00 / 夏 22:30–05:00 JST）**。2FA・人の監視が困難。

### 9-1. ① エントリーを絞るべき時間帯（結論: 寄り直後寄り＋ランチ除外）

- **現状 9:45–15:50 ET 通しは「最悪のランチ帯 11:30–13:30 ET」を丸ごと含む**。1分足SMAクロスは§02でも指摘の通りレンジ/チョップで構造的に負ける → **ランチ帯は SMAクロスが最も騙される時間**。
- 推奨ウィンドウ（市場構造に沿う）:

| 案 | ET ウィンドウ | 狙い |
|----|--------------|------|
| **A（推奨・トレンド帯集中）** | 9:45–11:30 + 14:00–15:45 | 最良帯と Power Hour に集中。ランチ(11:30–13:30)を除外 |
| B（朝のみ最小） | 9:45–11:30 | 最も信頼できる時間だけ。取引数は減るが質重視 |
| C（現状維持＋ランチ抑制） | 9:45–15:50 だが 11:30–13:30 はエントリー停止/閾値厳格化 | 既存構造を残しつつチョップ帯を回避 |

- **bot 設定への落とし方**（IBKR_CONTROL.csv 概念。実変更はたにさん承認＝🟡）:
  - 既存 `ibkr_start_hour_et`(9:45) は維持（寄り直後の高ボラ・LULD多発帯 9:30–9:45 を外す解釈で妥当）。
  - **ランチ除外パラメータを新設**（例: `ibkr_lunch_block_start_et=11:30` / `ibkr_lunch_block_end_et=13:30`）し、この間は新規エントリーをブロック。BTC側の `no_paper_hours` と同思想。
  - もしくは `ibkr_end_hour_et` の前にトレンド帯/Power Hour のみ許可するホワイトリスト時間帯方式。

### 9-2. ② 市場構造に沿った入口候補（SMAクロス単独からの脱却）

| 候補 | 内容 | 向く時間帯 | bot 実装の方向性 |
|------|------|-----------|----------------|
| **ORB（15分）** | 9:30–9:45 の高安を箱化し、9:45以降のブレイクで入る | 寄り直後 | 現 9:45 開始と整合。最初の15分レンジを state に保持し上/下抜けでエントリー。**出来高フィルタ必須** |
| **VWAP リバージョン** | VWAP からの乖離で逆張り→VWAP回帰を取る | レンジ日・ランチ前後 | VWAP を計算し「VWAP± n×ATR」で逆張り。トレンド日には弱い→レジーム併用 |
| **VWAP フォロー** | 価格が VWAP 上=ロング限定 / 下=ショート限定でクロスを使う | トレンド日・朝 | 既存SMAクロスに **VWAP 方向フィルタを上乗せ**（VWAP上ではロングのみ）。最小改修で騙し削減 |

- **最小改修の推奨**: いきなり手法総入れ替えではなく、**(a)ランチ帯ブロック + (b)VWAP方向フィルタ + (c)ORB箱の出来高条件** の3点を既存SMAクロスに被せるのが、parity を保ちつつ効く。
- 注: VIX≥30ブロックは§2-2の「高ボラ時は窓埋め/リバージョン優勢」と整合的（高ボラでトレンドフォロー型クロスを止めるのは妥当）。

### 9-3. ③ 深夜無人運用前提のリスク（ホルト・ギャップ・証拠金）

| リスク | 何が起きるか | bot 設定への落とし込み |
|-------|------------|----------------------|
| **個別ホルト/LULD（5分ポーズ）** | 保有中に5分約定不能→解除でギャップ。**損切りが滑る** | ①低浮動・低流動銘柄を**ユニバースから除外**（QQQ/SPY等の高流動に限定）。②ホルト検知時は新規停止 |
| **市場全体CB（7/13/20%）** | 全停止。Level3 はその日終了 | VIX≥30 ブロックに加え、**指数の急落%でグローバル停止**する閾値を持つ（例: S&P -3%でその日新規停止）。深夜は人が止められない |
| **オーバーナイト/時間外ギャップ** | 16:00以降の決算で翌寄りに窓。**SLを飛び越える** | **デイトレ厳守=引け前に全クローズ**（`ibkr_end_hour_et` 前に強制決済）。持ち越し禁止フラグ |
| **日中証拠金不足（新PDT規則§3-2）** | ポジ放置で証拠金割れ→口座制限(最大90日) | ロット小・1銘柄少量を維持。**証拠金使用率の上限ガード**を入れ、超過で新規停止 |
| **遅延/データ欠落（§7-2）** | paper/未購読で遅延データ→ズレ約定 | LIVE 前に**リアルタイムデータ購読を確認**。データ鮮度チェック（最終ティックの遅延秒数）で異常時停止 |
| **2FA・監視不能（深夜）** | 障害・暴落に人が即応不可 | ①日次損失上限(`ibkr_daily_loss_limit_usd=-20`)の厳守 + ②**ntfy通知 parity**（ホルト/CB/証拠金/強制クローズも必ず通知）。無音バグ防止 |

- **総括**: 深夜無人 × 1分足クロス × 約40銘柄 という構成は、**ホルト・ギャップ・薄商いの3点で最も事故りやすい**。優先度は (1)ユニバースを高流動に絞る → (2)ランチ帯と引け持ち越しを排除 → (3)ホルト/CB/証拠金の自動停止+通知 parity。いずれも**🟡実行前確認**事項（CSV変更/コード変更）。LIVE 切替は**🔴/領域1**でたにさん決裁。

---

## 参考ソース（URL一覧）

### 取引時間
- NYSE Holidays & Trading Hours: https://www.nyse.com/markets/hours-calendars
- Nasdaq Market Hours: https://www.nasdaq.com/market-activity/stock-market-holiday-schedule
- Fidelity「Stock market hours」: https://www.fidelity.com/learning-center/smart-money/stock-market-hours

### ORB / ギャップ / VWAP / 時間帯
- ForexTester「Opening Range Breakout」: https://forextester.com/blog/opening-range-breakout-trading-strategies/
- BuildAlpha「Opening Range Breakout Strategy」: https://www.buildalpha.com/opening-range-breakout/
- QuantifiedStrategies「Gap Trading Strategies」: https://www.quantifiedstrategies.com/gap-trading-strategies/
- StockCharts ChartSchool「Gap Trading Strategies」: https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies/gap-trading-strategies
- Trade That Swing「Intraday Repeating Patterns」: https://tradethatswing.com/stock-market-intraday-repeating-patterns/
- QuantPedia「Lunch Effect in the U.S. Stock Market」: https://quantpedia.com/lunch-effect-in-the-u-s-stock-market-indices/

### PDTルール（2026/6/4 改定）
- FINRA Regulatory Notice 26-10: https://www.finra.org/rules-guidance/notices/26-10
- FINRA「Understanding the New Intraday Margin Requirements」: https://www.finra.org/investors/insights/intraday-margin-requirements
- SEC SR-FINRA-2025-017（規則改正承認）: https://www.sec.gov/files/rules/sro/finra/2026/34-105226.pdf
- （歴史/旧規則）Pattern day trader — Wikipedia: https://en.wikipedia.org/wiki/Pattern_day_trader

### サーキットブレーカー / LULD
- SEC Investor.gov「Stock Market Circuit Breakers」: https://www.investor.gov/introduction-investing/investing-basics/glossary/stock-market-circuit-breakers
- NYSE「Market Resiliency During Times of Extreme Volatility」: https://www.nyse.com/network/article/nyse-increases-resiliancy-during-extreme-volatility
- Fidelity「Trading halts and market circuit breakers」: https://www.fidelity.com/learning-center/trading-investing/trading-halts

### IBKR
- IBKR Order Types and Algos: https://www.interactivebrokers.com/en/trading/ordertypes.php
- IBKR Commissions & Fees: https://www.interactivebrokers.com/en/pricing/commissions-home.php
- IBKR Market Data Pricing: https://www.interactivebrokers.com/en/pricing/market-data-pricing.php
- IBKR SmartRouting: https://www.interactivebrokers.com/en/trading/smart-routing.php

---

## 要点3行

1. **時間帯にエッジが偏在**: 寄り後 9:30–11:30 ET（≒冬23:30–01:30/夏22:30–00:30 JST）が最良、ランチ 11:30–13:30 ET は薄商いでチョップ＝1分足SMAクロスが最も負ける帯。
2. **市場構造のブレーキは二層**: 個別=LULD（バンド到達15秒で5分ポーズ・RTHのみ）、全体=CB（S&P -7/-13/-20%、20%はその日終了）。**PDTは2026/6/4に$25,000撤廃→日中証拠金不足のリアルタイム監視へ**（FINRA原典）。
3. **bot最優先策**: ①ユニバースを高流動(QQQ/SPY)に絞り低浮動株を排除 ②ランチ帯ブロック＋引け前強制クローズ ③ホルト/CB/証拠金不足の自動停止＋ntfy通知parity（深夜無人ゆえ無音事故が最大リスク）。
