# 02. テクニカル分析 — 米株デイトレ(1〜5分足)知識ベース

> 対象: 1〜5分足の米株デイトレード（IBKR bot 含む）
> 方針: 権威ソース2つ以上で裏取り、数値は原典引用。末尾に参考URL一覧。

---

## 結論先出し（このドキュメントの要旨）

1. **単一指標で勝てる手法は存在しない。** VWAP・移動平均・オシレーター・ボリンジャー・ATR はすべて「相場レジーム（トレンド or レンジ）」を前提に効き方が反転する。レジーム判定なしに同じロジックを回すと、片方の相場で稼ぎもう片方で吐き出す。
2. **短期足のSMAクロスはレンジで構造的に負ける。** MA はラグ指標であり、レンジでは2本のMAが絡み合い、各クロスが「数バーで戻る騙し（whipsaw）」になる（StockCharts / TradingSim）。1分足では特に頻発。
3. **損切りは固定%でなくATRベースが原理的に優れる。** ボラティリティに応じて損切り幅が自動で伸縮するため、静かな相場でのノイズ狩られと、荒い相場での即死を同時に減らせる（Fidelity / StockChartsほか）。
4. **上位足の方向に従う（マルチタイムフレーム）。** 下位足は上位足トレンドを「支持」する形でのみ使い、逆らうエントリーを弾く。これだけで偽シグナルが大幅に減るとされる（Tradeciety / heygotrade）。

---

## 1. VWAP（出来高加重平均価格）

### 計算と意味
- **計算式**: `VWAP = Σ(価格 × 出来高) / Σ(出来高)`。各約定の価格×出来高を当日始値から累積し、累積出来高で割る。**毎日リセット**する当日指標（StockCharts ChartSchool / Britannica Money）。
- 出来高が多い価格帯ほど重みが大きい。単純移動平均より「実際に資金が動いた価格」を反映するのが本質的な違い（StockCharts）。
- 機関投資家の執行ベンチマーク（「VWAPより良い値で約定できたか」）として使われるため、**価格が引き寄せられやすい**。

### デイトレでの使い方
| 状態 | 解釈 | 基本戦略 |
|------|------|---------|
| 価格 > VWAP | 買い手優勢・日中トレンド上 | ロング優先。押し目で拾う |
| 価格 < VWAP | 売り手優勢・日中トレンド下 | ショート優先。戻りで売る |
| VWAP上で反発継続 | トレンドフォロー局面 | VWAPを支持線として順張り |
| VWAP±乖離が大 | 過熱・割安/割高 | リバージョン（VWAPへの回帰）狙い |

- **2つのモードを使い分ける**:
  - **トレンドモード**: VWAPの傾きが明確で価格が片側に張り付く → VWAPタッチを押し目/戻り目として順張り。
  - **リバージョンモード**: レンジで価格がVWAPを挟んで上下 → VWAPから大きく乖離した時に「VWAPに戻る」方向へ逆張り（StockCharts / Schwab / Britannica）。
- どちらを使うかは後述の**レジーム判定**で決める。VWAPだけで両方やろうとすると損する。

### エントリー/エグジット例
- **順張りロング例**: 価格がVWAP上、上位足も上。VWAPまで押した後に直近高値を上抜けたらエントリー。SLはVWAP下＝ATRベース、TPは直近スイング高値 or 上位レジ。
- **リバージョン例（レンジ確認後のみ）**: 価格がVWAPから上方に大きく乖離（例: バンド外）→ 反転バーで戻り売り、ターゲット=VWAP。

---

## 2. 移動平均とクロスオーバー戦略の落とし穴

### なぜ短期足のSMAクロスは騙し（whipsaw）が多いか — 原理

1. **MAはラグ指標**: クロスは値動きが「すでに始まった後」に発生する。よって順張りでも遅れて入り遅れて出る（heygotrade / StockChartsの一貫した指摘）。
2. **レンジでは2本のMAが絡み合う**: 横ばい相場ではMAが平坦になり互いにもつれる。各クロスが「ブレイクに見えて数バーで戻る」騙しになる。これがwhipsaw（CrossTrade / chartswatcher）。
3. **短い時間足ほど偽シグナルが激増**: 「短い時間足は偽シグナルを著しく多く生み、口座を急速に削る」「choppyだと“千の切り傷による死（death by a thousand cuts）”に陥る」（TradingSim）。
4. **エビデンス**: 「生のクロスオーバー戦略は、choppy相場のwhipsawにより、ほとんどのレジームで損益トントンからややマイナス」「横ばい相場こそ最大の弱点で、サイドラインに退くべき」（heygotrade / chartswatcher / TradingSim）。クロスは**トレンド相場で良好・レンジで劣悪**という非対称性が一貫して報告されている。

### レンジでクロス戦略が機能しない理由（まとめ）
- レンジ = 方向性のない往復運動。MAクロスは「方向の転換」を捉える設計なので、**転換が連続発生する=偽シグナル連発**になる。
- タイトな損切りと組み合わせると、各偽シグナルが小さな確定損になり、回数で積み上がって致命傷になる。

### 落とし穴を減らす実務
- クロス単体で入らない。**レジームフィルタ（ADX等）でトレンド時のみ作動**させる。
- クロス + 価格構造（直近高安のブレイク）/ VWAP位置 / 上位足方向 の**多重確認**にする。
- SMAよりEMA（直近重視で反応速い）を使う場合もあるが、反応が速い=騙しも増えるトレードオフがある点に注意。

---

## 3. オシレーター（RSI / MACD / ストキャス・ダイバージェンス）

### 各指標の用途と限界
| 指標 | 主な用途 | 致命的な限界 |
|------|---------|-------------|
| **RSI(14)** | 過熱/反転の目安（>70過熱, <30売られ過ぎ） | 「RSI30が即反転を意味せず、70が即下落を意味しない」。強トレンドでは70/30に張り付き続ける（Wealthsimple / LiteFinance） |
| **MACD** | トレンド転換・モメンタム | ラグ指標。ダイバージェンスの出現頻度が低く、ピーク/ボトムの引き方が恣意的になりやすい（Forex Factory熟練者スレ） |
| **ストキャス** | 短期の過熱・反転、ダイバージェンス | 設定依存が非常に大きい。ダイバージェンス用途では比較的良いが調整必須（同上） |

### ダイバージェンスの限界（重要）
- **「ダイバージェンスは強トレンドで頻発するが機能しない」**。持続的トレンド（例: 円の一方向相場）では逆行サインが何度も出て全部失敗する（Forex Factory）。
- **「ダイバージェンスは口座より遠くまで伸びうる」** — 反転を待ち続けて大損する典型。さらに「ダブルトップ/ボトムの後は必ずダイバージェンスが出るので、それ自体は何も確認しない」（同上）。
- **原則**: ダイバージェンス“だけ”で入らない。**価格がトレンドラインを割る/MAをクロスする/直近サポートを破る**まで待つ（Traders Agency / Forex Factory）。

### エントリー/エグジット例
- **RSIリバージョン（レンジ限定）**: ADXが低くレンジ確認 → RSI<30 + サポート + 反転バーでロング、TP=レンジ中央/VWAP、SL=ATRベース。
- **MACDは確認専用**: 「MACDの強気クロスでも価格自体が下落トレンドなら偽シグナル」。価格構造・上位足の一致を必須にする（LiteFinance）。

---

## 4. ボリンジャーバンド / ATR（ボラティリティ計測と損切り）

### ボリンジャーバンド（John Bollinger 開発）
- **構造**: 中心線=20期間SMA、上下バンド=±2標準偏差（デフォルト）。**統計的に2σは値動きの約95%を含む**（StockChartsの記述）。
- **意味**: バンド幅=ボラティリティ。ボラ上昇で自動的に広がり、低下で収縮する（StockCharts / Fidelity / Wikipedia）。
- **スクイーズ**: バンドが収縮=低ボラ＝「大きな動きの前触れ」。**ただし方向は示さない**ため、スクイーズ単体でエントリーせずブレイク方向を待つ（Schwab / Bitsgap）。
- **デイトレ/スキャル**: 5分・1分足で20SMA±2σを使うのが一般的（DayTrading.com / Bitsgap）。
- **注意（レジーム依存）**: レンジでは「バンドタッチ→反対側へ回帰」が機能、強トレンドでは「バンドに沿って張り付く（band walking）」ため逆張りが死ぬ。

### ATR（Average True Range / J. Welles Wilder 開発）
- **True Range** = 次の3つの最大値（Wikipedia / Fidelity）:
  1. 当該期間の高値 − 安値
  2. |高値 − 前期間の終値|
  3. |安値 − 前期間の終値|
- **ATR** = TRをWilderの平滑移動平均でならしたもの。**デフォルト14期間**。平滑式: `ATR_t = (ATR_{t-1} × (n−1) + TR_t) / n`（初期値は最初のn本のTR単純平均）（Wikipedia / StockCharts）。
- ATRは**方向を示さない純粋なボラ尺度**。短い時間足では2〜10期間が推奨される（IG）。

### ATRベースの損切り幅設定
- **公式**:
  - ロング: `SL = エントリー価格 − (ATR × 倍率)`
  - ショート: `SL = エントリー価格 + (ATR × 倍率)`
- **倍率**: デイトレは短時間足のため **1.5〜2.0倍** が一般的（LuxAlgo / QuantVPS / calculator.academy）。
- **本質的な利点**: 「ATRストップは荒い相場で広がり、静かな相場で締まる」＝実際の値動きに整合（LuxAlgo / Optimus Futures）。固定%は相場状況を無視するため、静かな相場では狩られやすく荒い相場では即死しやすい。

---

## 5. サポレジ・トレンドライン・出来高プロファイルの基礎

### サポート/レジスタンス・トレンドライン
- **サポレジ**: 価格が繰り返し止まる/反発する水平帯。需給の記憶。デイトレでは前日高安・当日高安・寄り付き値・ラウンドナンバーが効きやすい。
- **トレンドライン**: 連続する押し安値（上昇）/ 戻り高値（下降）を結ぶ。**割れ=トレンド転換の確認材料**。オシレーターのダイバージェンスはトレンドライン割れと併用して初めて使える（Forex Factory / Traders Agency）。

### 出来高プロファイル（Volume Profile）
- 時間軸でなく**価格帯ごとの出来高**を横棒で表示。「最も資金が滞留した価格＝強いサポレジ」を可視化（TradingView / Schwab / OANDA）。
- **POC（Point of Control）**: 最大出来高の価格。最も注目された水準で、レンジ中は価格が引き寄せられる。リバージョンの基準やブレイク目標に使う。
- **バリューエリア（VA）**: 全出来高の約70%が取引された価格レンジ。**VAH（上限）/ VAL（下限）が動的サポレジ**。
- **HVN（高出来高ノード）**: 蓄積/分散が進んだ＝強いサポレジ帯。
- **LVN（低出来高ノード）**: 価格が素早く通過した薄い帯＝ブレイクが起きやすいゾーン。
- デイトレは**セッション・ボリューム・プロファイル（SVP）**が最適（TradingSim / Topstep）。

---

## 6. マルチタイムフレーム分析（上位足の方向に従う）

### 原則
- **下位足は上位足の方向を「支持」する形でのみ使う。矛盾させない**（heygotrade / cfi.trade）。
- **トップダウン**: 上位足で方向・重要レベルを把握 → 下位足でエントリー/エグジットのタイミングだけ取る（Tradeciety）。
- **時間足の組み合わせ**: 2〜3枚、概ね **1:4:16** の比率が推奨（heygotrade）。
  - 例（デイトレ）: 15分（方向）→ 5分（文脈）→ 1分（執行）。
- **効果**: MTFAは偽シグナルを最大80%除去するとの報告。複数足利用で勝率が単一足より改善するとされる（heygotrade）。※この勝率数値はマーケティング寄りソース由来のため、原理（上位足に従えば逆張り偽シグナルを弾ける）を採り、数値は鵜呑みにしない。

### 実務ルール例
- 上位足が上昇 → **下位足ではロングのみ**許可。下位足のデッドクロス“SELL”は**上位足が下落に転じるまで取らない**。
- 上位足がレンジ（ADX低） → 順張りを止め、レンジ手法（VWAP/VAリバージョン）に切替。

---

## 7. レジーム判定（トレンド vs レンジ）と手法の使い分け

### 見分け方
| ツール | トレンド | レンジ |
|--------|---------|--------|
| **ADX(14)**（Wilder） | **ADX > 25 = 強いトレンド**（Wilder） | **ADX < 20 = トレンドなし**。20〜25はグレーゾーン（StockChartsが引用するWilder基準） |
| **+DI / −DI** | +DI>−DI=上昇 / +DI<−DI=下降 | DI同士が絡む |
| **MAの傾き** | 明確に上/下を向く | 平坦・もつれる |
| **VWAP** | 価格が片側に張り付く | VWAPを挟んで往復 |
| **ボリンジャー** | バンドウォーク（張り付き） | バンド間を往復 |

> ADXは**方向ではなく強度**を0〜100で測る（Wilder, 1978）。多くのアナリストは閾値に20を使う（StockCharts）。

### レジーム別に有効な手法
| レジーム | 有効 | 機能しない（やってはいけない） |
|---------|------|------------------------------|
| **トレンド（ADX>25）** | MAクロス順張り、VWAP押し目/戻り、バンドウォーク追随、MACDトレンドフォロー | RSI過熱逆張り、ダイバージェンス逆張り、VWAP/バンドへのリバージョン |
| **レンジ（ADX<20）** | VWAP/VA/POCへのリバージョン、RSI過熱逆張り、ボリンジャー両端の逆張り | **MAクロス（whipsaw地獄）**、ブレイク順張り |

- **核心**: 同じ指標でもレジームで効き方が反転する。**まずレジームを判定し、それから手法を選ぶ**のが全TAの前提。

---

## 8. このbotへの紐付け（IBKR bot 専用分析）

### 現状（前提）
- ロジック: **1分足 SMA fast(5)/slow(20) クロス** + VWAPゲート + council（順張り必須）+ VIX<30。
- リスク: **SL −0.5% 固定 / TP +1.0% 固定**。
- 観測された負け方: **デッドクロスSELLを7連続→全逆行ストップ**（1分足ノイズ × タイトSL）。

### ① 1分足SMAクロスがなぜ負けるか（TA原理での説明）
- **MAはラグ指標** → クロス発生時点で初動は終わっている。1分足では初動が一瞬で終わり、入った直後に戻されやすい（heygotrade / StockCharts）。
- **レンジでfast(5)/slow(20)が絡み合う** → クロスが連続発生し、各々が数バーで戻る**whipsaw**。「7連続デッドクロスSELL→全逆行」はまさにレンジでのwhipsawの教科書的症状（CrossTrade / TradingSim）。
- **1分足は偽シグナルが激増** → 「choppyだと千の切り傷で死ぬ」状態。タイトSLがその切り傷を確定損に変換している（TradingSim）。
- **結論**: 「レジーム判定なしの1分足SMAクロス」は、レンジ相場で構造的に負ける設計。bot の連敗はパラメータ不良でなく**手法とレジームのミスマッチ**。

### ② レンジ/トレンド判定を入れるべき理由
- SMAクロスは**トレンドでのみ機能・レンジで劣悪**という非対称性が一貫報告されている（heygotrade / chartswatcher）。
- よって **ADX(14) ゲートを必須化**する:
  - **ADX > 25 のときだけクロスSELL/BUYを許可**（Wilder基準）。
  - **ADX < 20 のレンジではクロスを全面ブロック**し、エントリー見送り or リバージョン手法に切替。
- これで「7連続デッドクロスSELL」のようなレンジ連敗を入口で遮断できる。bot に既にある chop フィルタ思想（ATR低=chop記録）と整合し、ADXを足すことで**方向性のない相場の判定精度**が上がる。

### ③ ATRベースSLが −0.5%固定より優れる理由
- 固定%は**ボラティリティを無視**する。静かな相場では−0.5%がノイズ幅の内側に入り**簡単に狩られ**、荒い相場では−0.5%が浅すぎて**即死**する。
- **ATRストップは相場に応じて自動伸縮**するため、ノイズ狩られと即死を同時に減らせる（LuxAlgo / Optimus Futures / Fidelity）。
- **提案**: `SL = エントリー − (ATR(14) × 1.5〜2.0)`（ショートは + 側）。デイトレ標準倍率は1.5〜2.0（LuxAlgo / QuantVPS）。
  - TPも `ATR × 倍率` で対称化すれば、現行の R:R 2:1（−0.5/+1.0）を**ボラ適応で維持**できる（例: SL=1.5ATR, TP=3.0ATR）。
  - 1分足のATRが極端に小さい時はノイズ帯。**最小ATR下限**を設け、それ未満ならエントリー見送り（chopフィルタと同思想）。

### ④ マルチタイムフレームで上位足に逆らうSELLを弾く方法
- **上位足トレンドフィルタを追加**:
  - 上位足（例: **15分足**）の方向を判定（15分SMA20の傾き or 15分VWAPに対する価格位置 or 15分ADXの+DI/−DI）。
  - **上位足が上昇のとき、1分足デッドクロスSELLを禁止**（ロングのみ許可）。逆も同様。
- これにより「上位足上昇トレンド中の1分ノイズ・デッドクロス連発SELL」を入口で全弾する。council の「順張り必須」を**時間軸横断**に拡張する形。
- 推奨組み合わせ: **15分（方向）→ 5分（文脈/VWAP）→ 1分（執行）**（1:4:16比、heygotrade）。

### 推奨改修サマリ（優先順）
| 優先 | 改修 | 期待効果 | 根拠 |
|------|------|---------|------|
| 1 | **ADX(14)ゲート**: ADX<20でクロス全ブロック | レンジ連敗（7連続SELL型）を入口遮断 | Wilder / StockCharts |
| 2 | **上位足(15分)方向フィルタ**: 逆行クロスSELL禁止 | 上位足逆らいSELLを全弾 | Tradeciety / heygotrade |
| 3 | **ATRベースSL/TP**（1.5〜2.0×ATR, R:R維持） | ノイズ狩られ＆即死を同時低減 | LuxAlgo / Fidelity |
| 4 | **最小ATR下限**でchop時エントリー見送り | 薄商い・低ボラの千切り損を回避 | TradingSim |

> 注: 上記はTA原理に基づく**提案**。CONTROL/IBKR_CONTROLパラメータ変更・bot.pyコード変更・デプロイは要確認（🟡）。実装前にスペック表（IBKR_AGENT_SPEC.md）確認・バックテスト・バージョン上げを行うこと。

---

## 参考ソース（URL一覧）

### VWAP
- StockCharts ChartSchool — VWAP: https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/volume-weighted-average-price-vwap
- Charles Schwab — Volume-Weighted Indicators: https://www.schwab.com/learn/story/how-to-use-volume-weighted-indicators-trading
- Britannica Money — VWAP: https://www.britannica.com/money/volume-weighted-average-price

### 移動平均クロス / whipsaw
- StockCharts ChartSchool — Price-to-MA Crossovers: https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies/moving-average-trading-strategies/how-to-trade-price-to-moving-average-crossovers
- TradingSim — Simple Moving Average Guide: https://www.tradingsim.com/blog/simple-moving-average
- CrossTrade — Moving Average Crossover: https://crosstrade.io/learn/trading-strategies/moving-average-crossover
- heygotrade — Understanding Moving Average Crossover: https://www.heygotrade.com/en/blog/understanding-moving-average-crossover/

### オシレーター / ダイバージェンス
- Wealthsimple — MACD and RSI: https://www.wealthsimple.com/en-ca/learn/macd-and-rsi
- LiteFinance — RSI vs MACD: https://www.litefinance.org/blog/for-beginners/best-technical-indicators/rsi-vs-macd/
- Forex Factory — MACD/Stochastic/RSI/Divergence: https://www.forexfactory.com/thread/177812-help-regarding-macd-stochastic-rsi-divergence
- Traders Agency — RSI Divergence Strategy: https://tradersagency.com/blog/rsi-divergence-strategy-rsi-macd

### ボリンジャーバンド / ATR
- StockCharts ChartSchool — Bollinger Bands: https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/bollinger-bands
- Charles Schwab — Bollinger Bands: https://www.schwab.com/learn/story/bollinger-bands-what-they-are-and-how-to-use-them
- Wikipedia — Average True Range: https://en.wikipedia.org/wiki/Average_true_range
- StockCharts ChartSchool — ATR/ATRP: https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/average-true-range-atr-and-average-true-range-percent-atrp
- Fidelity — Average True Range (PDF): https://www.fidelity.com/bin-public/060_www_fidelity_com/documents/AverageTrueRange.pdf
- LuxAlgo — ATR Dynamic Stop Loss: https://www.luxalgo.com/blog/average-true-range-dynamic-stop-loss-levels/
- QuantVPS — ATR Stop-Loss Placement: https://www.quantvps.com/blog/using-average-true-range-for-stop-loss-placement
- IG — ATR Indicator: https://www.ig.com/en/trading-strategies/what-is-the-average-true-range--atr--indicator-and-how-do-you-tr-240905

### レジーム判定（ADX）
- StockCharts ChartSchool — Average Directional Index (ADX): https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/average-directional-index-adx
- heygotrade — ADX Trend Strength: https://www.heygotrade.com/en/blog/average-directional-index-adx/

### 出来高プロファイル / サポレジ
- TradingView — Volume Profile basic concepts: https://www.tradingview.com/support/solutions/43000502040-volume-profile-indicators-basic-concepts/
- Charles Schwab — Volume Profile Indicator: https://www.schwab.com/learn/story/using-volume-profile-indicator
- OANDA — Volume Profile Explained: https://www.oanda.com/us-en/trade-tap-blog/trading-knowledge/volume-profile-explained/
- TradingSim — Volume Profile Day Trading: https://www.tradingsim.com/blog/advanced-day-trading-strategies-using-volume-profile

### マルチタイムフレーム
- Tradeciety — Multiple Time Frame Analysis: https://tradeciety.com/how-to-perform-a-multiple-time-frame-analysis
- heygotrade — Multi-Timeframe Analysis: https://www.heygotrade.com/en/blog/multi-timeframe-analysis-explained-for-traders/
- cfi.trade — Multiple Time Frame Analysis: https://cfi.trade/en/educational-articles/what-is-technical-analysis/multiple-time-frame-analysis

---

## 要点3行
1. 全TAは「レジーム（トレンドADX>25 / レンジADX<20, Wilder基準）」次第で効き方が反転する。判定→手法選択の順が大原則。
2. 1分足SMAクロスはレンジでwhipsawし構造的に負ける（bot の7連続SELL逆行はこの典型）。ADXゲート＋上位足(15分)方向フィルタで逆行クロスを入口遮断すべき。
3. −0.5%固定SLはボラ無視で狩られ/即死を招く。`SL=ATR(14)×1.5〜2.0`に置換し、R:R 2:1をボラ適応で維持するのが原理的に優れる。
