# 08 BTCカタリスト & オンチェーン/フロー指標 — BTCデイトレ知識ベース

> 対象: BTC bot（Ouroboros / bitFlyer FX_BTC_JPY = Crypto CFD / SMA5/20・5分足 / 9:00–17:00 JST稼働 / LIVE）
> 作成: 2026-06-12 / 米株版 `05_fundamentals_catalysts.md` のBTC対応版。市場構造は `07_btc_market_structure.md` を参照
> 出典は末尾「参考ソース」を参照（日程・数値は原典引用）

---

## 結論先出し（要旨）

1. **BTCは2020年以降「米株のリスク資産」として動く**。IMF分析ではクリプトファクターは世界のテックファクター・小型株ファクターと最も強く相関（機関投資家の取引量は2020Q2→2021Q2で約$25B→$450B超、+1700%超）。FOMC・CPI・雇用統計は米株同様にBTCの「予測不能な瞬間ジャンプ」を起こす。**ただしBTCは24時間市場なので、発表の瞬間（FOMC=翌3:00 JST等）に即座に動き、JST 9–17の稼働帯には「残存影響（消化された後の値動き）」が来る**。
2. **デイトレに直接効くのは「フロー系」**: ①現物ETF日次フロー（前日分がJST朝までに確定→9:00稼働前にチェック可能） ②funding rate（過熱=清算カスケードの前兆。bitFlyer Crypto CFDは06:00/14:00/22:00 JST授受で、**14:00はbotの稼働時間内**） ③清算データ・OI。
3. **オンチェーン指標（取引所流入/流出・クジラ）は5分足デイトレには遅すぎる**。日次〜週次の「地合い・リスクフィルター」としてのみ有効。誤シグナルも多い（ウォレット内部移動等、警報の約30–40%は市場に影響しない移動）。
4. **現botへの示唆**: ①FOMC明けの朝はトレンドレジーム化しやすく平均回帰（SMAクロス）前提が崩れる→縮小/AIゲート厳格化 ②ETF大幅流出日（特に5日連続流出）は売り圧バイアスとして朝チェック ③14:00 JSTのfunding授受前後はポジション調整ノイズ→既存の`no_paper_hours="11,14,16"`の14時ブロックと整合 ④SKIP_NEWSにFOMC/CPI/NFP・大型清算・ハッキング・SEC発表の追加を提案。

---

## 1. マクロイベントのBTC即時影響（FOMC・CPI・雇用統計）

### 1.1 発表タイミング（JST併記）と稼働時間との関係

> JST = ET + 14時間（米国夏時間/EDT, 3月第2日曜〜11月第1日曜）。冬時間（EST）は +15時間。

| 指標 | 発表時刻(ET) | JST(夏) | JST(冬) | bot稼働帯(9–17 JST)との関係 |
|------|------------|---------|---------|---------------------------|
| **FOMC声明** | 14:00 ET（年8回・会合2日目） | **翌3:00** | **翌4:00** | 稼働外。ただし**約5–6時間後の9:00寄りに残存影響** |
| **FRB議長会見** | 14:30 ET | 翌3:30 | 翌4:30 | 同上 |
| **CPI** | 8:30 ET（毎月中旬） | **21:30** | **22:30** | 稼働外。**約11時間後の翌朝9:00に残存影響** |
| **PCE** | 8:30 ET（毎月） | 21:30 | 22:30 | 同上 |
| **雇用統計(NFP)** | 8:30 ET（毎月第1金曜） | 21:30 | 22:30 | 同上（翌営業日=月曜朝に持ち越しの場合も） |

- **株式市場と違い、BTCは発表の「その瞬間」に取引されている**。米株は時間外で板が薄いが、BTC無期限先物・現物は24時間フル稼働なので、初動・行き過ぎ・反転が深夜（JST）のうちに進行する。
- 高頻度データ研究では、**FOMC金利決定のサプライズ1標準偏差で発表前ボラティリティが+0.31%上昇**。ボラはCPI・FOMCとも「発表前から」上がり始める（出典: SCIRP高頻度研究 / ScienceDirect）。
- **CPI単体のBTCへの影響は研究上はミックス**（「無視できる」とする研究もある）。ただし2024年以降のETF時代は機関フロー経由で株式との連動が強まり、実務上はCPIサプライズ日にBTCも大きく動く（出典: ScienceDirect / CoinGecko / arXiv 2501.09911）。

### 1.2 株式と相関が強まった構造（近年）

| 時期 | 構造 | 根拠 |
|------|------|------|
| 〜2019 | 株式とほぼ無相関（「デジタルゴールド」論） | IMF WP/2023/163 |
| 2020〜 | 機関投資家参入で**リスク資産化**。クリプトファクターはテック・小型株ファクターと最強相関。機関の取引量は2020Q2→2021Q2で約$25B→$450B超 | IMF WP/2023/163 |
| 2024.1〜（現物ETF後） | **ETFが株式市場との「配管」になり相関がさらに上昇**（Nasdaq100/S&P500との相関がETF承認後に顕著に増加） | arXiv 2512.12815 |

→ **含意**: 米金利・米物価指標は「BTCに関係ないマクロ」ではなく、**QQQと同じ感応度で扱う**。FOMCタカ派サプライズ→BTC売り、ハト派→BTC買い、が基本線。

---

## 2. 現物ETF（IBIT等）の日次フロー

### 2.1 仕組みとタイミング

- 米現物BTC ETFは**2024年1月に取引開始**。**IBIT（BlackRock）が全体の約45%のシェアで最重要**（2026年4月例: 月間流入$2.44Bのうち IBIT $1.71B ≒ 70%）（出典: Phemex / KuCoin）。
- **日次フローは米市場クローズ後に確定・公表**される。設定/解約（create/redeem）はT+1なので「公表されるフロー＝前営業日の機関行動」（出典: NYDIG / Phemex）。
- **JST換算: 米クローズ=5:00 JST(夏)/6:00 JST(冬)→フロー集計は数時間以内に各社サイトに反映**。つまり**botの9:00 JST稼働開始前に前日フローが確認できる**。

### 2.2 確認ソース（具体URL）

| ソース | URL | 特徴 |
|--------|-----|------|
| **Farside Investors** | https://farside.co.uk/btc/ | 発行体別の日次フロー表。2024年1月のローンチ以来の全履歴 https://farside.co.uk/bitcoin-etf-flow-all-data/ |
| **The Block** | https://www.theblock.co/data/etfs/bitcoin-etf/spot-bitcoin-etf-flows | チャートで視覚確認 |
| **SoSoValue** | https://sosovalue.com/assets/etf/us-btc-spot | ダッシュボード形式 |
| **CoinGlass** | https://www.coinglass.com/etf/bitcoin | フロー+保有量。API有 |
| **Glassnode** | https://studio.glassnode.com/charts/institutions.UsSpotEtfFlowsNet?a=BTC | ネットフロー時系列 |

### 2.3 価格への影響（使い方と限界）

- **フローは「先行指標ではなく確認指標」**。価格が先・フローが後（ラグあり）。単日フローで方向を当てるのは不可（出典: Phemex / KuCoin）。
- 強いシグナルは**連続性**: 「**5営業日以上連続の流出**」は機関センチメント転換のサインとして扱う（出典: Phemex）。
- マクロ逆風（金利上昇等）が支配的な局面では、流入が続いても価格が上がらないことがある。

→ **デイトレでの使い方**: 単日±$100M程度はノイズ。**大幅流出日（目安: ネット-$500M超 or 5日連続流出）の翌日は「売り圧バイアス・戻り売り優勢」の地合い**として、BUYシグナルの信頼度を一段下げる。

---

## 3. Funding Rate（無期限先物の資金調達率）

### 3.1 意味

- 無期限先物（perp）には限月がないため、**先物価格を現物に係留するために、乖離に応じてロング⇄ショート間で定期的に資金を授受**する仕組み。先物>現物（プレミアム）ならロングがショートに支払う（正のfunding）。
- **正のfunding持続＝ロング過剰（強気過熱）/ 負のfunding＝ショート過剰（弱気・パニック）**。

### 3.2 過熱のサイン・清算カスケードの前兆（数値目安）

| 状態 | 8時間あたりfunding | 解釈 |
|------|-----------------|------|
| 中立 | 0.01%前後（ベースレート） | 健全 |
| 過熱の入口 | **0.10%超** | ローカル天井と重なりやすい（出典: Bitget Academy） |
| ユーフォリア | **0.15–0.20%** | レバロング過剰。**10–30%級の調整に先行した事例多数**（出典: Bitget Academy / ForkLog） |
| パニック | 大きく負 | ショート過剰→ショートスクイーズ（急騰）警戒 |

- **前兆の組み合わせ**: 「OI（建玉）が過去最高圏」×「fundingが極端」×「現値の5–10%下に清算クラスター」→ 小さな下げが強制清算の連鎖（カスケード）に発展しやすい（出典: XT Research / Gate Wiki）。
- 確認ソース: **CoinGlass** https://www.coinglass.com/FundingRate （funding・OI・清算ヒートマップ）/ **MacroMicro** https://en.macromicro.me/charts/49213/bitcoin-perpetual-futures-funding-rate

### 3.3 bitFlyer Crypto CFD のfunding制（前提整理）

- bitFlyerは**2024年3月28日18:00にLightning FX（とSFD制度）を廃止し、同日21:00からbitFlyer Crypto CFDを提供開始**（出典: bitFlyer公式PDF 2024-03-04 / 2024-04-02、CoinPost）。
- Crypto CFDでは旧SFD（現物乖離5%超でペナルティ）に代わり、**CFD価格と現物価格の乖離に基づく資金調達率（funding）を8時間ごとに授受**する制度＋サーキットブレーカーを導入（出典: bitFlyer公式PDF / bitbank plus）。
- **授受タイミングは 06:00 / 14:00 / 22:00 JST（8時間ごと）**。このうち **14:00 JST はbot稼働時間内（9–17 JST）に入る唯一の授受時刻**。
- 含意: funding支払いを避ける/受け取るためのポジション調整が**授受時刻の直前直後**に集中しやすく、短期的な需給ノイズ（実勢と無関係な小反転・ヒゲ）が出やすい。

---

## 4. オンチェーン指標の基礎（取引所フロー・クジラ）

### 4.1 主要指標

| 指標 | 意味 | 確認ソース |
|------|------|-----------|
| **取引所流入（Inflow）** | 個人ウォレット→取引所への送金。**売り準備の可能性** | CryptoQuant https://cryptoquant.com/asset/btc/chart/exchange-flows |
| **取引所流出（Outflow）** | 取引所→コールドウォレット。**長期保有=売り圧低下（強気）** | 同上 / Glassnode |
| **Exchange Whale Ratio** | 取引所流入上位10件/全流入。クジラ主導の流入検知 | CryptoQuant https://cryptoquant.com/asset/btc/chart/flow-indicator/exchange-whale-ratio |
| **大口送金アラート** | 大型トランザクションの即時通知 | Whale Alert https://whale-alert.io/ （X: @whale_alert） |

- 背景: **BTCアドレスの約2%が総供給の70%超を支配**しており、クジラ動向は需給の主役（出典: Bitget Academy）。
- 統計的には「価格もみ合い中に4–8週間流出が続く→その後四半期内に約65%のケースでラリー」といった**中期傾向**が報告されている（出典: Bitget Academy）。

### 4.2 デイトレへの有効性と限界（重要）

- **限界1: 速度**。オンチェーンデータはブロック確認・集計を経るため分単位の精度がなく、**5分足SMAクロスの判断材料としては遅すぎる**。
- **限界2: 誤シグナル**。取引所のホット⇄コールド内部移動・カストディの顧客資金集約など、**警報の約30–40%は市場に影響しない移動**（出典: Bitget Academy 2026）。「取引所への大口入金=売り」とは限らない。
- **限界3: 単発では方向を当てられない**。単一トランザクションでなく**数日間の継続フロー**のみが意味を持つ（出典: Ledger Academy / BingX）。
- → **結論: オンチェーンは「日次の地合いフィルター」**。デイトレ実務では (1)テクニカル (2)マクロ (3)funding/センチメント と組み合わせ、単独でトレードしない（出典: BingX / CoinCodex）。

---

## 5. 規制・ニュースカタリスト（即時性が最大）

### 5.1 種類と即時性

| カタリスト | 即時性 | 例 |
|-----------|--------|-----|
| **政府・大統領発言（関税・規制）** | **秒〜分**。最速・最大 | 2025-10-10 トランプ大統領が対中100%追加関税を表明→**24時間で約$19B（約2.8兆円）・延べ160万口座が強制清算（史上最大）。BTC約-14%、ETH約-21%**（出典: Bloomberg / SBI VCトレード / CoinPost） |
| **SEC・規制当局の決定** | 分〜時間 | ETF承認/却下、取引所提訴、ステーブルコイン規制 |
| **取引所・ブリッジのハッキング** | 分〜時間 | 大型流出報道→当該銘柄・市場全体の急落 |
| **大型清算イベント** | 分（カスケード進行中） | funding過熱+OI高水準時に発生しやすい（§3.2） |
| **企業・国家の購入発表** | 時間 | 財務省的買い（Strategy等）、国家準備金 |

### 5.2 2025-10-10の教訓（フラッシュクラッシュの構造）

- 発表は**JST深夜〜早朝**（米時間金曜日中）に始まり、清算カスケードは数時間継続。**24時間市場ゆえ「東京が寝ている間に構造が壊れ、朝9時には別のレジームになっている」**。
- 清算規模約$19Bは過去最大（従来最大の数倍）。**こうした日はSMAクロスの平均回帰前提が完全に崩れ、ATRも桁違いに膨らむ**→ ATRベースSL（バックテストで有効性確認済み）が固定SLより構造的に正しい理由の極端例。

---

## 6. Fear & Greed Index（botはcfg_score取得済）

### 6.1 計算（alternative.me 公式メソドロジー）

| 構成要素 | 重み | 内容 |
|---------|------|------|
| ボラティリティ | 25% | 現在ボラ・最大DDを30/90日平均と比較。急騰=恐怖 |
| モメンタム/出来高 | 25% | 現在出来高・勢いを30/90日平均と比較。異常高=強欲 |
| ソーシャル | 15% | X(Twitter)のハッシュタグ・言及速度 |
| ドミナンス | 10% | BTCドミナンス上昇=アルト回避（恐怖）と解釈 |
| Google Trends | 10% | 検索量・関連語の変化 |
| アンケート | 15% | 現在停止中 |

- 0=Extreme Fear 〜 100=Extreme Greed。**日次更新**（出典: alternative.me）。API: https://api.alternative.me/fng/

### 6.2 使い方と限界

- **逆張りの地合い指標**: Extreme Fear(〜25)は「売られすぎ・拾い場」、Extreme Greed(75〜)は「過熱・調整警戒」の歴史的傾向。研究ではF&Gと暗号資産間の価格同調性に**U字型関係**（極端な恐怖・強欲の両端で全銘柄が一方向に動きやすい）（出典: ScienceDirect, Finance Research Letters）。
- **限界**: ①日次更新でイントラデイの解像度がない ②構成の大半が価格由来（ボラ・モメンタム）で**価格の後追い** ③BTC中心設計。→ **5分足の売買トリガーには使えない。AIゲートの特徴量・極端値（<20, >80）での縮小フィルターが適所**（現行のcfg_score利用と整合）。

---

## 7. BTC版VIX — Deribit DVOL

- **DVOL**: Deribitが算出する**30日先のインプライド・ボラティリティ指数**（VIXと同じ思想。オプション価格から逆算する将来期待ボラ）。世界のBTCオプションの約9割がDeribitで取引されるため代表性が高い（出典: Deribit Insights）。
- **日次期待変動への換算: DVOL ÷ 19.1（=√365）**。例: DVOL=57 → 1日±3%が「織り込み」（出典: Deribit Insights）。
- 確認: https://www.deribit.com/statistics/BTC/volatility-index / TradingView `DVOL` / Glassnode。
- **使い方**: 米株のVIXゲート（IBKR botのVIX≥30ブロック）に相当する「嵐警報」として使える。DVOLが急騰している日＝織り込みボラが大きい日は、±0.14〜0.3%の値幅を狙う5分足戦略にはノイズ過多。**DVOL/19.1 が日次ATR%の数倍に膨れている日は縮小**が合理的。

---

## 8. サイクル要因 — 半減期・マイナー売り圧（デイトレ関連は簡潔に）

- **半減期**: 約4年ごとに新規発行が半減（直近は2024年4月、報酬6.25→3.125 BTC）。次回は2028年想定。**価格への影響は月〜年単位**で、デイトレの時間軸には直接効かない。
- **マイナー売り圧**: 半減期後はマイナー収益が即座に半減し（hashpriceは2024年4月以降USD建てで-57%）、マージン圧縮で売り圧が増えるが、**発行量自体も半減しているため絶対売却量は減る**（出典: Coinbase Institutional / Blockspace）。これも日次以下では無視してよい。
- **唯一のデイトレ接点**: 半減期「当日」はイベント性のボラ・出来高増があるため、ニュースイベント日として扱う程度で十分。

---

## 9. 【bot紐付け】現BTC botへの具体提案

> 前提: bitFlyer FX_BTC_JPY(Crypto CFD) / SMA5/20・5分足 / 9:00–17:00 JST / SKIP_NEWS実装済 / cfg_score取得済 / AIゲート・chopフィルタあり。
> 【最新バックテスト発見 2026-06-12】5年17,626トレードで固定SL-0.14%は一貫負け→**ATR×2.0 SLでプラス転換**。米株で有効なトレンド整合フィルタはBTC(JST9-17=アジア薄商い帯)では逆効果＝**平均回帰優位**。

### 9.1 ① FOMC/CPI翌朝のJST 9–17時帯への残存影響 — 「寄り9時のWR 66.7%」は何を拾っているか

- **構造**: 米株クローズ=5:00 JST(夏)。FOMC(翌3:00 JST)・CPI(21:30 JST)の初動〜米引けまでの値動きは、**9:00 JSTの時点で「行き過ぎ＋薄商いアジア帯」**という形で残る。`07_btc_market_structure.md` の通りJST 9–17はアジアセッションのド真ん中＝平均回帰優位。
- **仮説**: 9時のWR 66.7%は「**米セッションのオーバーシュートを、流動性が薄く新規材料が出ないアジア朝に平均回帰で巻き戻す**」エッジを拾っている可能性が高い。つまり9時の好成績は「前夜に動いた日ほど」出やすいはず。
- **提案**:
  1. **検証**: trade_logの9時台トレードを「前夜にFOMC/CPI/NFPがあった日」と「無風日」に分けてWR/平均損益を比較する（どちらがエッジ源か特定）。
  2. **FOMC明けの朝だけは例外扱いを検討**: FOMC直後はトレンド継続（レジーム転換）になることがあり、平均回帰前提のSMAクロスが踏まれる。**FOMC翌営業日の9:00–11:00は lot縮小 or AIゲート閾値+0.05** をobserveから試す。
  3. CPI/NFPは発表が21:30 JSTで稼働終了(17:00)の4.5時間後→翌朝までに約11時間経過しており残存影響はFOMCより小さい。優先度はFOMC>NFP>CPI。

### 9.2 ② ETFフロー大幅流出日の注意

- フローは**9:00稼働前に確定済み**（米クローズ後集計）。朝チェックに組み込める唯一の「機関フロー」情報。
- **提案**: 朝の`/status`またはbot起動時に Farside/CoinGlass APIで前日ネットフローを取得し、
  - **ネット-$500M超の流出 or 5営業日連続流出** → 当日を「売り圧バイアス日」とし、BUY側のAIスコアに減点（IBKRの`daily_move`ガードと同思想）またはobserveログ（`ETF_OUTFLOW_OBSERVE`）で記録から開始。
  - 単日±$100M程度はノイズとして無視（過剰フィルター化を避ける。BTC週10件の取引数下限ルールに留意）。

### 9.3 ③ funding過熱・14:00 JST授受タイミングとSMAクロスの騙され

- **14:00 JSTはbitFlyer Crypto CFDのfunding授受がbot稼働時間内に来る唯一の時刻**。授受前後はfunding回避/獲得のポジション調整で実勢と無関係な小反転が出やすく、SMA5/20クロスの騙され（whipsaw）要因になる。
- **現行`no_paper_hours="11,14,16"`の14時ブロックはこの構造と整合**（14時WRが悪かった理由の候補）。14時ブロックを外す検討をする場合はfunding授受の存在を必ず考慮すること。
- **funding過熱の利用**: CoinGlass等でグローバル（Binance）fundingが**0.10%/8h超**の日は「レバロング過剰→下方向の清算カスケードリスク高」。**過熱日はBUYシグナル縮小・SELL側は通常通り**、の非対称フィルターをobserveで検証する価値あり。逆に大きく負のfunding日はショートスクイーズ（急騰）警戒でSELL縮小。

### 9.4 ④ SKIP_NEWSに追加すべきイベント（具体リスト）

| 追加候補 | タイミング(JST) | 理由 |
|---------|---------------|------|
| **FOMC声明・会見の翌営業日 9:00–11:00** | 年8回 | 残存トレンドで平均回帰が崩れる（§9.1） |
| **CPI・PCE・NFP当日の稼働終盤**（夏16:30–17:00は不要だが、冬時間で発表が22:30でも前倒しヘッジの動きは夕方から出る）→ 最低限**翌朝をワッチ** | 毎月 | 発表前ポジション調整・翌朝残存 |
| **大型清算カスケード進行中**（例: 1時間清算額がCoinGlassで異常値、またはATR%が直近中央値の3倍超） | 不定期 | 2025-10-10型。SMAクロス無効化・ATR-SLでも追いつかない |
| **大型ハッキング・取引所障害の報道** | 不定期 | 既存SKIP_NEWSのキーワードに hack / exploit / halted / insolvency 系を含める |
| **SEC・米政府の暗号資産重要発表**（ETF判断・大統領令・規制法案採決） | 不定期 | 秒単位の即時ジャンプ |
| **半減期当日**（次回2028年想定） | 4年毎 | イベント性ボラのみ |

- 実装は既存SKIP_NEWS経路への追加が最小変更。新規分岐を足す場合は**parityルール**（ntfy通知・CSVログ・state更新を既存経路と同等に）を遵守。
- いずれも**まずobserveモードで記録→ブロック件数と機会コストを`/filter`で評価→block化**の既存手順に従う（chopフィルタ・IBKR P2フィルタと同じ運用）。

---

## 参考ソース（URL一覧）

**マクロイベント・株式相関**
- IMF WP/2023/163 "The Crypto Cycle and US Monetary Policy": https://www.imf.org/-/media/files/publications/wp/2023/english/wpiea2023163-print-pdf.pdf
- NY Fed Staff Report No.1052 "The Bitcoin–Macro Disconnect": https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr1052.pdf
- Do FOMC and macroeconomic announcements affect Bitcoin prices? (ScienceDirect): https://www.sciencedirect.com/science/article/abs/pii/S154461231930159X
- Modeling Cryptocurrency Market Volatility during FOMC Announcements (SCIRP): https://www.scirp.org/journal/paperinformation?paperid=136168
- Intraday macroeconomic news and crypto volatility (ScienceDirect): https://www.sciencedirect.com/science/article/pii/S1059056025006720
- FOMC meetings impact on crypto (CoinGecko): https://www.coingecko.com/learn/fomc-meetings-impact-on-crypto
- Institutional Adoption and Correlation Dynamics (arXiv 2501.09911): https://arxiv.org/pdf/2501.09911
- Impact of Bitcoin ETF Approval on Hedging Properties (arXiv 2512.12815): https://arxiv.org/html/2512.12815v1

**現物ETFフロー**
- Farside Investors BTC ETF Flow: https://farside.co.uk/btc/ （全履歴: https://farside.co.uk/bitcoin-etf-flow-all-data/）
- The Block — Spot Bitcoin ETF Flows: https://www.theblock.co/data/etfs/bitcoin-etf/spot-bitcoin-etf-flows
- SoSoValue US BTC Spot ETF: https://sosovalue.com/assets/etf/us-btc-spot
- CoinGlass Bitcoin ETF: https://www.coinglass.com/etf/bitcoin
- Glassnode US Spot ETF Net Flows: https://studio.glassnode.com/charts/institutions.UsSpotEtfFlowsNet?a=BTC
- NYDIG — Predicting Bitcoin ETF Fund Flows: https://www.nydig.com/research/predicting-bitcoin-etf-fund-flows
- Bitcoin ETF Flows Explained (Phemex): https://phemex.com/academy/bitcoin-etf-flows-explained
- ETF Inflows/Outflows and BTC Price (KuCoin): https://www.kucoin.com/blog/how-bitcoin-etf-inflows-and-outflows-impact-btc-price-in-2026

**Funding rate・清算**
- Bitcoin Funding Rates: Track & Interpret (Bitget Academy): https://www.bitget.com/academy/12560603875487
- Funding rate と価格反転 (ForkLog): https://forklog.com/en/the-funding-rate-how-it-helps-anticipate-price-reversals-in-bitcoin-and-ethereum/
- BTC Futures Microstructure: Liquidation Cascades, Funding Regimes (XT Research): https://medium.com/@XT_com/bitcoin-futures-market-microstructure-liquidation-cascades-funding-regimes-and-open-interest-978b107b4889
- Derivatives signals: funding/OI/liquidations (Gate Wiki): https://www.gate.com/crypto-wiki/article/how-to-interpret-crypto-derivatives-market-signals-funding-rates-open-interest-and-liquidation-data-explained-20251227
- MacroMicro BTC Perpetual Funding Rate: https://en.macromicro.me/charts/49213/bitcoin-perpetual-futures-funding-rate
- CoinGlass Funding Rate: https://www.coinglass.com/FundingRate

**bitFlyer制度（SFD廃止→Crypto CFD）**
- bitFlyer公式 2024-03-04 Lightning FX廃止・Crypto CFD提供開始: https://bitflyer.com/pub/20240304-Announcement_Service_Launch_CFD_Discontinuation_FX_ja.pdf
- bitFlyer公式 2024-04-02 Crypto CFD提供開始のお知らせ: https://bitflyer.com/pub/20240402-Announcement_Service_Launch_CFD_ja.pdf
- bitFlyer Crypto CFD 製品ページ: https://bitflyer.com/ja-jp/s/crypto-cfd
- CoinPost — SFD廃止発表とCrypto CFD: https://coinpost.jp/?p=514157
- bitbank plus — bitFlyer Crypto CFD発表解説: https://bitbank.cc/knowledge/breaking/article/ez2tg1d9p23

**オンチェーン・クジラ**
- CryptoQuant Exchange Flows: https://cryptoquant.com/asset/btc/chart/exchange-flows
- CryptoQuant Exchange Whale Ratio: https://cryptoquant.com/asset/btc/chart/flow-indicator/exchange-whale-ratio
- Whale Alert: https://whale-alert.io/
- Crypto Whale Alerts 2026 (Bitget Academy): https://www.bitget.com/academy/crypto-whale-alerts
- How to Track Whale Movements (Ledger Academy): https://www.ledger.com/academy/topics/crypto/how-to-track-crypto-whale-movements
- Whale Alerts for trading (BingX): https://bingx.com/en/learn/article/how-to-use-whale-alerts-for-crypto-trading
- Forecasting BTC volatility from whale transactions (arXiv 2211.08281): https://ar5iv.labs.arxiv.org/html/2211.08281

**2025-10-10 清算イベント**
- Bloomberg — 暗号資産市場で過去最大の強制清算: https://www.bloomberg.com/jp/news/articles/2025-10-11/T3Y41IGPQQ7800
- SBI VCトレード週間レポート（2025.10.5–10.11）: https://www.sbivc.co.jp/market-report/a24w3pi3ww
- CoinPost — 史上最大フラッシュクラッシュ後の市場: https://coinpost.jp/?p=657535
- マネクリ（マネックス証券）— 10月10日 過去最大の清算: https://media.monex.co.jp/articles/-/27997

**Fear & Greed Index**
- Alternative.me Crypto Fear & Greed Index（メソドロジー記載）: https://alternative.me/crypto/fear-and-greed-index/
- Alternative.me API: https://alternative.me/crypto/api/
- U-shaped relationship between F&G and price synchronicity (ScienceDirect): https://www.sciencedirect.com/science/article/abs/pii/S1544612323011352
- F&G Index Explained (Caleb & Brown): https://calebandbrown.com/blog/fear-and-greed-index/

**DVOL**
- DVOL — Deribit Implied Volatility Index (Deribit Insights): https://insights.deribit.com/exchange-updates/dvol-deribit-implied-volatility-index/
- Deribit launches volatility index: https://insights.deribit.com/exchange-updates/deribit-launches-volatility-index/
- Deribit BTC DVOL チャート: https://www.deribit.com/statistics/BTC/volatility-index
- Glassnode DVOL: https://studio.glassnode.com/charts/derivatives.DvolOhlc?a=BTC

**半減期・マイナー**
- Coinbase Institutional — Bitcoin Halving and Miner Economics: https://www.coinbase.com/en-ar/institutional/research-insights/research/market-intelligence/bitcoin-halving-and-miner-economics
- Blockspace — The impact of the halving, one year on: https://blockspace.media/insight/the-impact-of-the-halving-one-year-on/
- CME Group — Bitcoin Halving 2024: https://www.cmegroup.com/articles/2024/bitcoin-halving-2024-this-time-its-different.html
- AMINA Bank — Post Halving Miners Landscape: https://aminagroup.com/research/post-halving-bitcoin-miners-landscape/

---

## 要点3行

1. BTCは2020年以降テック株と同じリスク資産（IMF/arXiv）— FOMC(翌3:00/4:00 JST)・CPI/NFP(21:30/22:30 JST)は深夜に初動が出て、JST 9–17稼働帯には「残存影響」が来る。9時WR 66.7%は米セッション行き過ぎの平均回帰巻き戻しを拾っている仮説→FOMC翌朝だけはトレンド化で例外（縮小候補）。
2. デイトレに効くフロー系は3つ — ①ETF日次フロー（9:00稼働前に確定。-$500M超/5日連続流出で売り圧バイアス）②funding rate（0.10%/8h超=過熱・清算カスケード前兆。bitFlyer CFDは06/14/22時授受で**14時は稼働内**=現行14時ブロックと整合）③清算/OI（CoinGlass）。オンチェーン（取引所フロー/クジラ）は5分足には遅く、警報の30–40%は誤シグナル=日次地合いフィルター限定。
3. SKIP_NEWS追加候補 — FOMC翌朝・CPI/PCE/NFP・大型清算カスケード（2025-10-10は24hで$19B清算/BTC-14%）・ハッキング・SEC/政府発表。いずれもobserve→/filter評価→block化の既存手順で。F&G(cfg_score)は<20/>80の極端値フィルター、DVOL÷19.1=日次期待変動はBTC版VIXゲートとして利用可。
