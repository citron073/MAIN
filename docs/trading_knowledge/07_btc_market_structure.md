# 07. BTC 24時間市場の構造 — 知識ベース

> 対象: BTC/暗号資産のデイトレード（bitFlyer FX_BTC_JPY bot / 5分足 SMA5/20クロス）
> 方針: 権威ソース2つ以上で裏取り、規則・数値は原典引用。時刻は JST 基準（必要に応じ UTC/ET 併記）。末尾に参考URL一覧。
> 作成: 2026-06-12 JST
> ⚠️ 重要訂正: **bitFlyer の SFD は廃止済み**。Lightning FX は 2024年3月28日に廃止され、後継の「bitFlyer Crypto CFD」（商品コードは `FX_BTC_JPY` のまま継続・API互換）は SFD ではなく**ファンディングレート制**（8時間ごと授受）。古い「SFD 5%発動」情報がネットに大量に残っているため原典で確認すること。

---

## 結論先出し（このドキュメントの要旨）

1. **BTCは24時間市場だが、エッジ（出来高・ボラ・流動性）は米国時間に極端に偏在する。** 学術研究は「欧州・米国株式市場の取引時間帯に出来高・ボラが顕著に上昇し、アジア株式市場のオープンの影響は限定的（出来高はほぼ無反応）」と報告（Finance Research Letters / Eross et al.系研究）。Kaiko は ETF 時代以降「米国時間外の取引シェアは過去最低、アジア・欧州時間帯に流動性ギャップ」と報告。
2. **本botの稼働 9:00–17:00 JST は、グローバルで最も薄い「アジアセッション」にほぼ一致する。** 薄い時間帯はトレンドが持続しにくく**平均回帰が優位**になりやすい——これは「上位MAトレンド整合フィルタがBTC 5分足で逆効果（+64%→-19%）」という 2026-06-12 バックテスト発見と整合する（§9-5）。
3. **週末は出来高が平日の半分〜6割に落ち、スプレッドは2倍超に拡大。** CME先物の週末ギャップは「約77%が埋まる」（$500未満の小ギャップは85%が1〜2週間で充填）。bot は土日も板が薄い前提で扱う（現状は曜日制御なし・時間制御のみ）。
4. **BTC特有の急変メカニズム＝清算カスケード。** 高レバレッジのパーペチュアル先物で強制決済が連鎖し、数分で数%動く（2025年10月10日には約$19Bが一掃される史上最大の清算イベント）。5分足SMAクロスはこの「垂直の動き」に構造的に弱い（遅行エントリー→即SL）。固定SL -0.140% はノイズ幅未満で狩られる——ATR連動SLへの移行が正解（バックテスト: 固定SL -137% → ATR×2.0 で +134%）。
5. **bitFlyer価格はグローバル価格（Binance等）の「後追い」**。価格発見は海外パーペチュアル・米国ETF/現物が主導し、bitFlyerのJPY価格は裁定で追随する。CFDと現物の乖離はファンディングレート（06:00/14:00/22:00 JST 授受、上限±0.375%）で抑制される。**14:00 JST の授受時刻は bot 稼働時間内**にある点に注意。

---

## 1. 24時間365日市場のセッション構造

### 1-1. 3大セッションの JST 換算

BTC自体に「立会時間」はないが、参加者（株式市場・機関投資家・マーケットメイカー）の活動時間で事実上のセッションが生まれる。

| セッション | 現地の株式市場時間 | JST換算 | BTCでの特性 |
|-----------|------------------|---------|------------|
| **アジア** | 東京 9:00–15:30 / 香港 9:30–16:00 / シンガポール 9:00–17:00 | **9:00–17:00 JST** | 出来高・ボラとも最小。学術研究で「アジア株オープンの影響は出来高にほぼ無し」。レンジ・平均回帰相場になりやすい |
| **欧州** | ロンドン 8:00–16:30（GMT/BST） | **夏 16:00–0:30 / 冬 17:00–1:30 JST** | 出来高・ボラが立ち上がる。ロンドンオープン（16–17時 JST）で方向感が出始める |
| **米国** | NYSE/Nasdaq 9:30–16:00 ET | **夏 22:30–5:00 / 冬 23:30–6:00 JST** | **出来高・ボラ・流動性とも最大**。米経済指標・ETFフロー・マクロが価格発見を主導 |

- 欧米株式市場は夏時間（DST）あり・日本は無しのため、**JST換算は年2回ズレる**（米: 3月第2日曜〜11月第1日曜が EDT）。
- 重複帯: **欧州×米国の重複（22:30–0:30 JST 夏）が世界で最も厚い時間**。逆に**米国クローズ後〜アジア午前（6:00–15:00 JST）が最も薄い**。

### 1-2. セッション跨ぎの流動性変化（データ）

- 学術研究（Finance Research Letters, "Time-of-day periodicities of trading volume and volatility in Bitcoin exchange"）: 出来高・ボラは1日を通じて**逆V字型**で、**欧州・米国株式市場の取引時間帯にピーク**。「アジア株式市場のオープンにはボラがわずかに反応するのみで、出来高はほぼ無反応」。出来高とボラには双方向の因果関係。
- Kaiko Research（BTC ETFs' Impact on Spot Market Structure）: 現物ETF承認後、**米国時間への取引集中が進み、米国時間外の取引シェアは過去最低**。「USD市場はアジア・欧州の時間帯に明確な流動性ギャップ」。米国時間集中は価格発見・流動性を改善する一方、**日中ボラの増大要因**にもなる。
- 実務的帰結: **同じSMAクロスでも、セッションによって「トレンドが続く確率」が全く違う**。厚い時間（米国）はフォロースルーが出やすく、薄い時間（アジア）は initial move が吸収されて往復ビンタ（whipsaw）になりやすい。

---

## 2. 時間帯別のボラティリティ・出来高パターン

| 時間帯 (JST) | グローバル状態 | ボラ/出来高 | 5分足デイトレへの含意 |
|--------------|---------------|------------|---------------------|
| 6:00–9:00 | 米国クローズ直後 | 低下していく | 動意薄。前夜の余韻 |
| **9:00–15:00** | **アジアのみ** | **最低水準** | レンジ・平均回帰。トレンドフォローは whipsaw 多発 |
| 15:00–16:00 | アジア引け〜欧州前 | 谷（最も薄い帯の一つ） | bot の 14–16h ブロックはこの「昼の谷」と整合 |
| **16:00–17:00** | **ロンドンオープン** | 立ち上がり | 方向感が出始める。bot 稼働終了間際 |
| 17:00–22:30 | 欧州メイン | 中 | 欧州指標・先物オープンで動く |
| **21:30–22:30** | 米指標時間（CPI 8:30 ET = 21:30 JST 夏） | スパイク | 指標ギャンブル帯 |
| **22:30–1:00** | **米国オープン×欧州重複** | **最大** | 出来高・トレンドとも最強。ただし急変も最大 |
| 1:00–5:00 | 米国単独〜クローズ | 高→減衰 | FOMC（3:00 JST 夏）はここ |

- S&P Global（Bitcoin Volatility Trends）も、BTCの実現ボラが伝統市場のリスクイベント・米国時間に同期して動くことを確認。
- **bot実績との照合**: 時間帯別WR 10h=51% → 11h=47% → 12h=45% → 13h=44% → 14–16h<42%（ブロック済）という**単調劣化は「アジア午前の動意が午後に向けて枯れていく」出来高カーブそのもの**。10時が最良なのは東京株オープン（9:00）直後の余熱とアジア勢の新規フローが残っているため、と整合的に説明できる。

---

## 3. 週末効果（土日の薄商い・窓・週明けギャップ）

- **出来高**: 週末は平日比 **20〜40%減**（Phemex）。ETF時代はさらに顕著で、**平日出来高は週末の約2倍**が常態化（機関フローが平日米国時間に集中するため）。
- **スプレッド/板**: BTC-USDT の平均スプレッドは平日 0.012% → **週末 0.028% と2倍超に拡大**。$100K規模の実効デプスは約9%劣化、取引コストは平均11%増（DailyCoin/Kaiko系データ）。
- **窓（ギャップ）**: BTC現物は24時間動くが、**CME先物（金曜クローズ〜月曜オープン）に「窓」が開く**。統計では**約77%のCMEギャップは最終的に埋まり、$500未満の小ギャップは85%が1〜2週間以内に充填**（CryptoSlate / QuantifiedStrategies）。週末に現物が大きく動くと、月曜の機関フローが「窓埋め方向」に働きやすい。
- **週末の値動きの質**: 薄い板では小口注文でも価格が飛ぶ。「週末の急騰・急落は出来高の裏付けが薄く、月曜に否定されやすい」が共通見解。
- **botへの含意**: 現botは曜日制御なし（毎日 9–17 JST 稼働）。**土日アジア時間は1週間で最も薄い時間帯**であり、whipsaw・スリッページとも最悪条件。土日の成績を分離集計し、悪ければ曜日フィルタ（土日縮小/停止）は検討に値する。

---

## 4. bitFlyer FX_BTC_JPY 特有の制度（SFD→Crypto CFD移行後）

### 4-1. 制度の現在地（2026-06時点・原典確認済み）

| 項目 | 内容 |
|------|------|
| 商品 | **bitFlyer Crypto CFD**（2024-03-28 18:00 に Lightning FX を廃止して開始。商品コード `FX_BTC_JPY` は当面継続・API互換） |
| **SFD** | **廃止**。旧制度は「現物と5%以上乖離時に約定ごとに発生」（乖離5–10%: 0.25%、10–15%: 0.5%、15–20%: 1%、20%以上: 2%） |
| **ファンディングレート** | SFDの後継の乖離防止機構。**毎日 06:00 / 14:00 / 22:00 JST** に、CFD価格と Lightning現物価格の乖離（8時間平均）から算出した金銭を授受。CFD>現物なら買い建玉保有者が支払い・売り建玉保有者が受取り |
| 同・上限/下限 | レート上限 **±0.375%**。平均乖離が -0.040%〜+0.060% の範囲では固定 **0.010%** |
| 授受額 | ファンディングレート × 保有建玉数量 × 現物価格 |
| 満期/ロールオーバー | 満期1日の契約。**毎営業日 18:00 JST に満期→自動で1営業日延長** |
| レバレッジ | 個人 **2倍**（必要証拠金50%） |
| ロスカット | 維持証拠金率 **50%** 到達で強制決済 |
| メンテナンス | **毎日 04:00–04:10 JST**（bot稼働時間外） |
| API | Lightning FX と互換。`getfundingrate`（market_type=FX）で次回授受レートを取得可能 |

### 4-2. 現物乖離・スプレッド特性

- CFD価格は Lightning現物（BTC/JPY）から乖離しうるが、ファンディングレートが乖離を現物側へ引き戻す圧力になる（乖離が大きい側のポジション保有にコストが発生するため）。
- 旧Lightning FX時代は現物比 +5〜10% の恒常乖離が問題化し SFD が導入された経緯がある（CRIPCY / CoinPost）。現行制度では乖離は大幅に縮小しているが、**急変時は一時的に乖離が拡大**する。
- **botへの含意**:
  - **14:00 JST の授受時刻は稼働時間内**。授受時刻直前は「コスト回避の建玉整理フロー」で小さな歪みが出ることがある（グローバルのパーペチュアルでも funding 授受時刻前後の歪みは既知のパターン）。
  - botの保有は分〜時間単位なので、06:00/22:00 は跨がないが **14:00 を跨ぐポジションはファンディング授受の対象**になる（通常は 0.010%〜の小コストだが、相場過熱時は最大±0.375%）。
  - 18:00 ロールオーバー・04:00 メンテはともに稼働時間外で現状影響なし。稼働時間を延長する場合はこの2つを避けて設計する。

---

## 5. BTC特有の値動き

### 5-1. ラウンドナンバー（心理的節目）

- $10K刻み・$50K/$100K などの**ラウンドナンバーに指値・損切り・利確注文が集中（クラスタリング）**し、自己実現的なサポート/レジスタンスになる（Cryptohopper / UEEx ほか実務系で共通見解）。
- JPY建て（bitFlyer）では **1,000万円・100万円刻み**にも国内勢の注文が集まる。USD建ての節目とJPY建ての節目が重なる価格帯は特に反応しやすい。
- 5分足デイトレへの含意: **節目直前の順張りエントリーは「節目の壁」に刺さりやすい**。TP+0.220%先に大節目がある場合は到達確率が下がる。

### 5-2. 清算カスケード（funding / レバレッジ起因の急変）

- パーペチュアル先物は満期がない代わりに**ファンディングレートで現物にアンカー**される。レバレッジが積み上がった状態で価格が動くと、**強制決済（清算）→成行売り→さらに下→次の清算ライン到達**という自己強化ループ（清算カスケード）が発生する（KuCoin / MetaMask / XT解説）。
- **規模感**: 2025年10月10日のフラッシュクラッシュでは**数時間で約$19Bの建玉が清算**され、過去最大の約9倍という規模だった（insights4VC / Coinchange）。
- **前兆指標**: ファンディングレートの極端な正値（ロング過熱）は局所天井・ロングスクイーズの脆弱性を示す。OI（建玉残高）急増+高funding は警戒シグナル。
- 米株との違い: **サーキットブレーカーが無い**。LULDのような強制ポーズが存在せず、垂直に数%動く。「ブレーキの無い市場」前提のリスク設計が必須。

### 5-3. 先物主導の価格発見

- 価格発見はグローバルのパーペチュアル先物（Binance等）と、ETF時代以降は米国現物・ETFフローが主導。現物・国内JPY市場は基本的に**追随側**。
- 急変はまず先物で起き、裁定を通じて bitFlyer に波及する。つまり **bitFlyerの5分足に現れた急変は「既に起きたことの写像」**であり、そこからの順張りは構造的に遅い。

---

## 6. Binance/グローバル価格と bitFlyer 価格の関係

- 学術研究（Makarov & Schoar, Journal of Financial Economics "Trading and arbitrage in cryptocurrency markets"）: 2017-12〜2018-02 に**国境を跨ぐ価格乖離から最低$2Bの裁定機会**が存在。日本は米国比で平均約10%のプレミアムが付いた時期もある（資本規制・出入金摩擦が原因）。**同一国内の取引所間乖離は平均1%未満**。
- 2026年現在は裁定の高度化で乖離は大幅縮小（主要コインのネットスプレッドは0.3〜2.5%程度・国別取引所×グローバル取引所間が中心: CryptoTalkies）。
- 実務的帰結:
  - bitFlyer FX_BTC_JPY = 「**Binance USD価格 × USDJPY + 国内需給プレミアム**」の近似。**JPY建ての値動きには為替（USDJPY）成分が混入**する。
  - **Binanceデータでのバックテストが bitFlyer 実取引の近似として概ね有効**な根拠はこの強い裁定リンク（06_backtest_results.md の前提を支持）。ただし国内固有の薄さ・スプレッド・乖離スパイクは Binance データに現れない誤差要因。

---

## 7. マクロイベント（FOMC/CPI）の即時影響

- **時刻（JST）**: 米CPI = 8:30 ET発表 → **21:30 JST（夏）/ 22:30 JST（冬）**。FOMC声明 = 14:00 ET → **3:00 JST（夏）/ 4:00 JST（冬）**、議長会見はその30分後。**いずれも bot 稼働時間（9–17 JST）外**。
- **即時反応**: 学術研究（ScienceDirect "Do FOMC and macroeconomic announcements affect Bitcoin prices?"）は「FOMC発表後**約1分で価格調整が完了し、ボラは約15分高止まり、その後数時間は通常より高い水準**」と報告。FOMC当日のBTC日次ボラは通常日比50〜100%高いとの分析も（Investing.com）。CPI・FOMCは**発表前からボラが上昇**する（事前ポジショニング）。
- **逆の見解も併記**: NY連銀スタッフレポート（Benigno & Rosa, "The Bitcoin-Macro Disconnect", No.1052）は、BTCが大半のマクロニュースに対して**方向性のある系統的反応をほぼ示さない**「マクロとの分断」を報告。
- **統合解釈**: 方向は事前に読めない（分断）が、**ボラティリティは確実に上がる**（イベント研究）。デイトレ botにとっては「方向のエッジは無いがSLを狩られるリスクだけ増える」時間。
- **米株との相関**: BTCはグローバル流動性・米実質金利と連動し、リスクオン/オフ局面ではNasdaqと正相関が強まる。FOMC翌日のアジア時間（= bot稼働時間）は**前夜の方向を消化するギャップ・乱高下**が持ち込まれる点に注意。

---

## 8. 【bot紐付け】現BTC botへの具体提案

前提: bitFlyer FX_BTC_JPY / 0.001 BTC / SMA5/20クロス(5分足) / 稼働9:00–17:00 JST / SL-0.140%・TP+0.220% / trend_strength_min_er=0.30 / AIゲート0.70 / chopフィルタobserve / 週10件未満の過少取引が課題。

### 8-1. ① 9–17 JST はどのセッションか — 結論: **最も薄い「アジアセッション」のド真ん中。不利寄り、ただし「平均回帰向き」**

- 9:00–15:00 はアジア単独、15:00–16:00 は谷、16:00–17:00 だけロンドンオープンに掛かる。**グローバルの出来高ピーク（22:30–1:00 JST）を完全に外している**。
- 不利な点: 出来高薄→トレンド持続性が低い→SMAクロス順張りの期待値が出にくい。fill率も板の薄さの影響を受ける。
- 有利な点: ①急変（清算カスケード・マクロ指標）の大半が稼働時間外で起きる＝**テールリスクが構造的に小さい**。②人間が監視できる時間帯。③薄い時間は**平均回帰のエッジ**が立つ（§8-5）。
- **評価: 「順張りには不利・逆張り/平均回帰には適した時間帯」**。戦略をセッション特性に合わせる方が、時間帯を戦略に合わせるより筋が良い。

### 8-2. ② 稼働時間を変える/広げるなら

| 候補 | 時間 (JST) | 根拠 | 注意 |
|------|-----------|------|------|
| **A. 16:00–18:00 へ1h延長**（最有力） | 17:00→18:00 | ロンドンオープンの動意を取り切る。現WR最良の「セッション変わり目」の延長線 | 18:00 はCFDロールオーバー時刻。17:55までにクローズする設計に |
| B. 21:00–1:00 の夜間枠を**Shadowで**新設 | 米指標+米国オープン | 出来高・トレンドとも最大の時間帯。順張りSMAクロスが本来効くべき時間 | ボラが段違い→**固定SL -0.140%は即死**。ATR-SL前提でなければ不可。CPI時刻(21:30夏)は除外 |
| C. 9:00–10:00 の検証強化 | 現10h WR51%の前段 | 東京株オープン直後のフロー。9h追加(2026-05-24)の効果を継続検証 | — |
| D. 14–16h ブロック維持 | — | 「昼の谷」と整合。再開する根拠なし | — |

- 原則: 過少取引の解消は「薄い時間で無理に取る」より「**動く時間に枠を広げる（まずobserve/Shadowで）**」が定石。

### 8-3. ③ SFD発動時の注意 → **制度自体が廃止。現在はファンディングレート**

- 「SFD 5%乖離で発動」は**2024-03-28以前の旧情報**。現行 Crypto CFD では:
  - **14:00 JST の授受時刻を跨ぐ建玉はファンディング授受対象**（通常0.010%〜、上限±0.375%）。TP+0.220%の利幅に対し最大授受額は無視できない規模になりうるため、**相場過熱時（funding高騰時）は13:55前後の新規保有を避ける/手仕舞う**価値がある。
  - `getfundingrate` API（market_type=FX）で次回レートを事前取得できる。**高funding（例: |0.05%|超）をリスク指標としてAIゲートやchopフィルタの特徴量に加える**のは低コストで筋が良い。
  - 18:00 ロールオーバー・04:00–04:10 メンテは現稼働では無関係だが、稼働延長時は必ず避ける。

### 8-4. ④ 清算カスケード時の SMAクロス破綻リスク

- カスケードは**数分で数%**動く。5分足SMA5/20は構造的に遅行し、クロス確定時には動きの大半が終わっている → **エントリー直後に平均回帰の戻りを食らい即SL**が典型敗北パターン。
- 固定SL -0.140% はカスケード時のノイズ幅（1本で0.5–2%動く）に対して**桁違いに狭く、確実に狩られる**。バックテスト（Binance 5分足5年・17,626トレード）の「固定SL-0.14%は一貫して負け(-137%) / ATR×2.0でプラス転換(+134%)」はこの構造の定量証明。**BTC側もIBKR同様にATR連動SL（×2.0）へ移行すべき**（最重要の具体提案）。
- 防御策の優先順位: (1) **ATR-SL移行** (2) 直近N分の値動きが閾値超なら新規停止（IBKRの daily_move ガードのBTC版・クールダウン） (3) chopフィルタとは逆の「**高ボラ・スパイク直後ブロック**」をobserveで追加 (4) funding極端値での警戒（§8-3）。
- なお稼働9–17 JSTは大型カスケードの主戦場（米国時間）を外しているため被弾確率は低いが、**ゼロではない**（アジア時間発のフラッシュクラッシュも歴史上複数回ある）。

### 8-5. ⑤ 「BTC 5分足は平均回帰が強い」をセッション構造から説明できるか — **できる**

3つの構造要因が同じ方向を向く:

1. **薄いセッションでは initial move にフォロースルーが続かない。** トレンド持続には継続的な新規資金（機関フロー・ETF・マクロ筋）が必要だが、それは米国時間に集中（Kaiko）。bot稼働のアジア時間はその供給が無く、**動いた価格はマーケットメイカーの在庫調整と裁定で「適正値」に引き戻される** → 平均回帰。
2. **24時間連続市場には「寄り付き」が無い。** 米株の寄りはオーバーナイトの情報を一気に織り込む需給不均衡＝トレンドの発生源（ORBが効く理由）。BTCは情報が24時間連続的に織り込まれるため、**米株型の「セッション初動トレンド」が構造的に発生しにくい**。米株で有効だった上位MAトレンド整合フィルタがBTCで逆効果（+64%→-19%）になったのは、**「上位トレンド方向への押し目継続」より「行き過ぎの巻き戻し」が支配的**だから。
3. **学術的裏付け**: 高頻度研究（Wen et al. 2022, NAJEF）はBTC日中リターンに**モメンタムと反転（リバーサル）の両方**が存在し、流動性水準・ジャンプ・FOMCで切り替わると報告。QuantPediaも「BTCはトレンドフォローと平均回帰が時間軸・レジームで併存」と整理。さらに「15分足の切り替わり時点にプラスリターンが集中し、それ以外の分は平均マイナス」というマイクロ構造анomaly（turn-of-the-candle effect, t値9超）も、**短時間軸の値動きが「往復」中心**であることを示す。
- **統合結論**: 「平均回帰が強い」のはBTC全体の性質というより、**(a) 24時間市場に寄り付きトレンドが無いこと + (b) bot稼働がフォロースルー資金の無い薄いセッションであること**の合成。したがって——
  - アジア時間で戦い続けるなら: トレンド整合フィルタは入れない（バックテスト通り）。むしろ**逆張り系（行き過ぎ→戻り）ロジックのShadow検証**が次の一手。
  - 順張りSMAクロスを活かしたいなら: **米国時間（22:30–1:00 JST）へのShadow展開**が筋（フォロースルーが存在する時間で順張りする）。ただしATR-SL必須。

---

## 参考ソース（URL一覧）

### セッション構造・時間帯別パターン
- Time-of-day periodicities of trading volume and volatility in Bitcoin exchange (Finance Research Letters): https://www.sciencedirect.com/science/article/abs/pii/S1544612319301904
- 同論文 (ResearchGate): https://www.researchgate.net/publication/334727071_Time-of-Day_Periodicities_of_Trading_Volume_and_Volatility_in_Bitcoin_Exchange_Does_the_Stock_Market_Matter
- Kaiko Research — BTC ETFs' Impact on Spot Market Structure: https://research.kaiko.com/insights/btc-etfs-impact-on-spot-market-structure
- S&P Global — Bitcoin Volatility Trends: https://www.spglobal.com/en/research-insights/special-reports/bitcoin-volatility-trends-deep-dive

### 週末効果
- Phemex — Weekend Crypto Trading Explained: https://phemex.com/blogs/weekend-crypto-trading-explained
- CryptoSlate — CME's 24/7 crypto launch will kill Bitcoin's weekend gap: https://cryptoslate.com/cme-bitcoins-weekend-gap-dead-clearing-monday/
- QuantifiedStrategies — Weekend Effect In Bitcoin: https://www.quantifiedstrategies.com/weekend-effect-in-bitcoin/
- DailyCoin — Bitcoin's Weekend Gap: ETFs Shift Liquidity to U.S. Hours: https://dailycoin.com/bitcoins-weekend-gap-etfs-shift-liquidity-to-u-s-hours/

### bitFlyer 制度（SFD廃止・Crypto CFD）
- bitFlyer プレスリリース — Lightning FX廃止及びbitFlyer Crypto CFD提供開始: https://prtimes.jp/main/html/rd/p/000000101.000047991.html
- bitFlyer Crypto CFD ユーザーガイド（funding rate 06:00/14:00/22:00 JST・上限±0.375%等）: https://lightning.bitflyer.com/docs/crypto-cfd
- bitFlyer Lightning API 改定通知（FX_BTC_JPY コード継続・API互換）: https://bitflyer.com/pub/20240322-explanation-bitflyer-Lightning-API-comparison-en.pdf
- CRIPCY — bitFlyer価格乖離規制(SFD)の経緯: https://cripcy.jp/exchanges/bitflyer/bitflyer_regulations

### 清算カスケード・ラウンドナンバー
- KuCoin — Why Bitcoin Futures Trading Can Cause a Liquidation Cascade: https://www.kucoin.com/blog/en-why-bitcoin-futures-trading-can-cause-a-liquidation-cascade
- MetaMask — Perpetual futures liquidation explained: https://metamask.io/news/perpetual-futures-liquidation-mechanics
- insights4VC — Inside the $19B Flash Crash (2025-10-10): https://insights4vc.substack.com/p/inside-the-19b-flash-crash
- Cryptohopper — The Impact of Psychological Levels on Crypto Trading: https://www.cryptohopper.com/blog/the-impact-of-psychological-levels-on-crypto-trading-11398

### 裁定・グローバル価格リンク
- Makarov & Schoar — Trading and arbitrage in cryptocurrency markets (JFE): https://www.sciencedirect.com/science/article/abs/pii/S0304405X19301746
- 同論文 PDF (LSE): https://eprints.lse.ac.uk/100409/1/Cryptocurrency_Markets_JFE_final_v4.pdf

### マクロイベント
- Do FOMC and macroeconomic announcements affect Bitcoin prices? (ScienceDirect): https://www.sciencedirect.com/science/article/abs/pii/S154461231930159X
- NY Fed Staff Report No.1052 — The Bitcoin-Macro Disconnect (Benigno & Rosa): https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr1052.pdf
- Exploring volatility reactions in cryptocurrency markets using intraday macroeconomic news analysis (ScienceDirect): https://www.sciencedirect.com/science/article/pii/S1059056025006720

### 平均回帰・日中予測可能性
- Wen et al. — Intraday return predictability in the cryptocurrency markets: Momentum, reversal, or both (NAJEF): https://www.sciencedirect.com/science/article/abs/pii/S1062940822000833
- QuantPedia — Trend-following and Mean-reversion in Bitcoin: https://quantpedia.com/trend-following-and-mean-reversion-in-bitcoin/
- Turn-of-the-candle effect in bitcoin returns (PMC): https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10015199/

---

## 要点3行

1. bot稼働 9–17 JST はグローバルで最も薄いアジアセッション＝トレンド持続せず**平均回帰優位**（トレンド整合フィルタ逆効果のバックテスト結果と構造的に整合）。順張りを活かすなら米国時間 22:30–1:00 JST へのShadow展開、延長するならロンドンオープン 16–18時が候補。
2. **SFDは2024-03-28に廃止済み**。現行Crypto CFD（コードはFX_BTC_JPYのまま）はファンディングレート制（06:00/**14:00**/22:00 JST授受・上限±0.375%）で、**14:00授受は稼働時間内** → 高funding時は跨ぎ保有に注意・APIで事前取得可能。
3. 清算カスケード（例: 2025-10-10 $19B清算）には遅行SMAクロス+固定SL-0.140%は構造的に脆弱 → **ATR×2.0 SLへの移行が最優先の具体改善**（バックテストで-137%→+134%）。
