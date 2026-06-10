# 05 ファンダメンタルズ & カタリスト — 米株デイトレード知識ベース

> 対象: IBKR 米株デイトレードボット（Ouroboros / QQQ中心+約40銘柄, PAPER稼働中・未入金）
> 作成: 2026-06-11 / 出典は末尾「参考ソース」を参照（日程・数値は原典引用）

---

## 結論先出し（要旨）

1. **デイトレでファンダ分析は不要。だが「材料（カタリスト）による値動き」は必須知識**。財務諸表を読み込む必要はないが、「今日この銘柄/市場を動かす材料は何か」を把握しないと、テクニカルが効かない地雷日にエントリーしてしまう。
2. **決算・FOMC・CPI・PCE・雇用統計（NFP）は「予測不能な瞬間ジャンプ」を起こす**。1分足テクニカルが無力化する。決算前後のオーバーナイトはギャップで月単位の値動きが一晩に圧縮される。
3. **デイトレに効く一次情報は「日程」と「VIX」**。決算カレンダー・経済指標カレンダー・SEC EDGAR(8-K)を見て「いつ荒れるか」を先に押さえる。VIXは市場全体の30日先ボラ期待＝荒れ度のフィルター。
4. **現ボットへの示唆**: ①高イベント日（決算/FOMC/CPI/PCE/NFP）は新規エントリーを止めるか縮小 ②VIX≥30ブロックは「嵐警報」水準として妥当だが、20〜30の警戒帯も縮小対象に検討の余地 ③カタリスト主導日は1分足が効かない＝テクニカル前提が崩れる ④監視銘柄選定では決算日程・ベータ・流動性をファンダ要素として確認。

---

## 1. デイトレでファンダはどこまで必要か（スイング/長期との違い）

### 1.1 時間軸ごとのファンダの重み

| 時間軸 | 主な意思決定要因 | ファンダの役割 |
|-------|----------------|--------------|
| **デイトレ（数分〜数時間）** | 価格・出来高・板・**当日の材料による値動き** | バリュエーション分析は不要。ただし「決算日か」「指標発表日か」「ニュースが出たか」のイベント把握は必須 |
| **スイング（数日〜数週）** | テクニカル + **直近カタリストの方向（ガイダンス・PEAD等）** | 中程度。決算後ドリフト等を利用 |
| **長期投資（月〜年）** | **ファンダ（業績・成長・バリュエーション）** | 中核。PER/PSR/成長率/競争優位 |

### 1.2 「材料による値動き」が主とは

デイトレは「企業の本質的価値が割安か」ではなく、**「今、この銘柄/指数に資金と注目が集まり、ボラと流動性が出ているか」**で勝負する。
- 動かす源泉＝**カタリスト**: 決算、ガイダンス改定、M&A、格付け変更、FDA承認、経済指標、地政学ニュース。
- したがってデイトレーダーが見るべきファンダは「**割安かどうか**」ではなく「**今日この銘柄が動く理由があるか／動く時刻はいつか**」。
- 逆に言えば、**カタリストの無い静かな日**は値幅が出ずデイトレに不向き、**カタリスト過剰な日**（決算直後・FOMC直後）は値動きが暴れてテクニカルが効かない。両極端を避け「程よく動く」状態を狙う。

> NFP報告は通貨・株式・債券・商品・暗号資産の全市場を動かす（出典: Kiplinger / EBC）。指標は個別銘柄の話ではなく市場全体（SPY/QQQ）を一斉に揺らす点がデイトレ最大の注意点。

---

## 2. 決算（Earnings）前後の値動きと決算プレイの危険性

### 2.1 決算がなぜ危険か

- **オーバーナイト・ギャップ**: 決算は寄り付き前に「数ヶ月分の不確実性を一晩の再価格付けに圧縮」する。決算翌日に8%ギャップして寄ることもある（出典: tradingriot）。**1分足テクニカルでギャップは防げない**（場が閉まっている間に動く）。
- **インプライド・ムーブ（織り込み変動率）**: オプション価格が事前に「想定変動幅」を示す。実際の変動が織り込みを下回るのは約70〜75%（出典: collinseow / tradingriot）。つまり「動くと分かっていても方向は読めない」。
- **IVクラッシュ（ボラティリティ・クラッシュ）**: 決算通過後、IVが数時間で30〜50%低下（NVDA/TSLA等の高IV銘柄は40〜55%）（出典: volatilitybox）。オプションの建玉は決算通過だけで価値が溶ける。
- **PEAD（決算後ドリフト）**: 大きなポジティブ・サプライズ銘柄は60〜90日かけて上方に、ネガティブは下方にドリフトを続ける既知のアノマリー（出典: Wikipedia / DayTrading.com）。ギャップ方向に「続伸／続落」しやすく逆張りは危険。

### 2.2 デイトレでの決算の扱い

| 局面 | 推奨スタンス |
|------|------------|
| **決算発表当日（前後）** | 新規ポジションは原則回避。方向が読めずギャップ・IVクラッシュ・乱高下のリスクが集中 |
| **決算翌日以降のドリフト** | ギャップ方向への順張りは検討可（PEAD）。ただし逆張りは避ける |
| **決算を持ち越す（オーバーナイト）** | デイトレの原則に反する。最も避けるべき |

### 2.3 決算カレンダーの入手元（一次/準一次）

| ソース | URL | 用途 |
|--------|-----|------|
| **企業IRページ** | 各社 "Investor Relations" | 発表日時の一次情報（最も確実） |
| **SEC EDGAR Full-Text Search** | https://efts.sec.gov/LATEST/search-index?q= / https://www.sec.gov/cgi-bin/srqsb | 8-K（決算は Item 2.02 で開示） |
| **Nasdaq Earnings Calendar** | https://www.nasdaq.com/market-activity/earnings | 銘柄別の予定日（無料） |
| **取引所/ベンダーの経済・決算カレンダー** | TradingEconomics / 各証券会社 | 一覧確認 |

> 決算は 8-K の Item 2.02「Results of Operations and Financial Condition」で開示される。8-K は原則トリガー事象から**4営業日以内**の提出（出典: AssetRoom / SEC）。Regulation FD 絡みは即日〜翌朝提出もある。

---

## 3. 経済指標イベント（発表タイミング JST併記 と市場への影響）

> JST = ET + 14時間（米国夏時間/EDT, 3月第2日曜〜11月第1日曜）。冬時間（EST）は ET + 15時間。**米国夏時間か冬時間かで JST が1時間ずれる点に注意**。下表は夏時間(EDT)基準。

| 指標 | 発表元 | 発表時刻(ET) | 発表時刻(JST/夏) | 頻度・タイミング | 市場影響 |
|------|--------|-------------|-----------------|---------------|---------|
| **FOMC 声明** | Federal Reserve | **14:00 ET** | **翌3:00 JST** | 年8回・会合2日目 / 議長会見は14:30 ET(翌3:30 JST) | 最大級。金利・全資産 |
| **CPI（消費者物価）** | BLS | **8:30 ET** | **21:30 JST** | 毎月（翌月中旬） | 大。インフレ→利下げ観測 |
| **PCE（個人消費支出物価）** | BEA | **8:30 ET** | **21:30 JST** | 毎月（Personal Income & Outlays内） | 大。FRBが最重視する物価指標 |
| **雇用統計 / NFP** | BLS | **8:30 ET** | **21:30 JST** | 毎月**第1金曜**（祝日等で前後あり） | 最大級。全市場を動かす |

### 3.1 2026年 FOMC 会合日程（声明は2日目 14:00 ET / 翌3:00 JST）

> 出典: Federal Reserve FOMC calendar。

- 1/27–28, 3/17–18, 4/28–29, 6/16–17, 7/28–29, 9/15–16, 10/27–28, 12/8–9
- 声明: 各会合**2日目の 14:00 ET（翌 3:00 JST）**、議長会見 14:30 ET（翌 3:30 JST）

### 3.2 指標発表の市場への影響メカニズム

- **8:30 ET（21:30 JST 夏）発表の CPI/PCE/NFP** は、米株の**寄り付き前**（NYSE寄りは9:30 ET）に出る。プレマーケットで先物（ES/NQ）が瞬間的に大きく振れ、寄り後の最初の30〜60分が荒れる。
- **14:00 ET（翌3:00 JST 夏）の FOMC声明** は引け間際（NYSE引けは16:00 ET）。声明と14:30の会見で2段階に動き、**引けにかけて方向が定まらない**（whipsaw が頻発）。
- 共通点: **発表の瞬間にギャップ的ジャンプが起き、テクニカルの連続性が断たれる**。直前のサポート/レジスタンスやMAは無効化されやすい。

---

## 4. セクターローテーション・指数連動・ベータ

### 4.1 SPY / QQQ の関係とベータ

| 指標 | 値 | 出典 |
|------|----|------|
| SPY ベータ（対市場） | ≈ 0.96 | Validea |
| **QQQ ベータ（24ヶ月加重平均）** | **≈ 1.295** | Validea / macroaxis |
| QQQ–SPY 相関 | **0.87〜0.94**（時間軸で安定） | stockanalysis / etfdb |

- **QQQ は SPY より高ベータ（≈1.3倍動く）**。テック・グロース偏重で「Magnificent 7」の決算/AI物語/バリュエーション変化に敏感（出典: Validea / Seeking Alpha）。
- 個別銘柄の**ベータ**＝市場（SPY等）に対する感応度。ベータ1.5の銘柄はSPYが1%動くと約1.5%動く傾向。**高ベータ銘柄は値幅が出るがリスクも大きい**。
- デイトレでの使い方: トレーダーは**QQQをリーダー（先行）シグナル**として見て、**SPYを市場全体の確認**に使う（出典: bookmap）。個別銘柄の動きが指数と逆行/順行のどちらかで「個別材料か地合いか」を切り分ける。

### 4.2 セクターローテーション

- 経済局面に応じて資金がセクター間を移動する現象（グロース→バリュー、ディフェンシブ→景気敏感 等）。SPY/QQQの相対強弱を見ると資金の向きが読める（出典: bookmap）。
- デイトレ示唆: 監視銘柄が同一セクター（例: 半導体）に偏ると、**1つの材料で全銘柄が同時に動く＝分散が効かない**。セクター集中はリスク集約になる。

---

## 5. ニュースカタリストの種類と即時性

| カタリスト | 内容 | 即時性 | デイトレ影響 |
|-----------|------|--------|------------|
| **決算（Earnings）** | 8-K Item 2.02 | 発表瞬間（多くは寄り前/引け後） | 最大。ギャップ+IVクラッシュ |
| **ガイダンス改定** | 業績見通し上方/下方修正 | 即時（8-K/プレス） | 大。決算と同等の方向材料 |
| **M&A（買収/合併）** | 買収提案・合意 | 即時（8-K Item 1.01/2.01） | 被買収側は買収プレミアムで急騰しギャップ |
| **格付け変更** | アナリスト/格付機関の up/downgrade | 寄り前に出ることが多い | 中〜大。プレマーケットで方向付け |
| **FDA（医薬）** | 承認/非承認・治験結果 | 即時（バイオは値幅極大） | 極大。バイオは数十%ジャンプ |
| **指数入替** | S&P500等への組入/除外 | 発表後〜実施日 | 中。パッシブ買いで需給 |
| **地政学/規制** | 制裁・規制・要人発言 | 突発 | 市場全体（SPY/QQQ）を揺らす |

> 共通原則: **カタリストは「予告できる日程もの（決算/指標）」と「突発もの（M&A/地政学）」に分かれる**。前者は事前回避できる。後者は VIX や板の急変で事後検知するしかない。

---

## 6. 一次情報の入手元（具体URL付き）

| 種別 | ソース | URL |
|------|--------|-----|
| **SEC開示（8-K/10-Q/10-K）** | SEC EDGAR Full-Text Search | https://efts.sec.gov/LATEST/search-index?q= |
| 同 企業別検索 | SEC EDGAR company search | https://www.sec.gov/cgi-bin/browse-edgar |
| 同 最新提出 | SEC EDGAR latest filings | https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent |
| **企業IR** | 各社 Investor Relations ページ | （銘柄ごと） |
| **FOMC日程・声明** | Federal Reserve | https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm |
| **CPI日程** | BLS CPI Schedule | https://www.bls.gov/schedule/news_release/cpi.htm |
| **雇用統計(NFP)日程** | BLS Employment Situation Schedule | https://www.bls.gov/schedule/news_release/empsit.htm |
| **BLS全体日程** | BLS Selected Releases | https://www.bls.gov/schedule/news_release/current_year.asp |
| **PCE/GDP日程** | BEA News Schedule | https://www.bea.gov/news/schedule |
| **VIX** | Cboe VIX | https://www.cboe.com/tradable-products/vix/ |
| 同 履歴データ | FRED VIXCLS | https://fred.stlouisfed.org/series/VIXCLS/ |
| **決算カレンダー** | Nasdaq Earnings | https://www.nasdaq.com/market-activity/earnings |

> SEC提出期限（参考, 出典: AssetRoom/Mayer Brown）: 8-K=トリガーから4営業日以内 / 10-Q=四半期末から40日（Large Accelerated/Accelerated）〜45日（Non-Accelerated）/ 第4四半期は10-Qなし（10-Kが代替）。

---

## 7. VIX（恐怖指数）の意味とデイトレでの使い方

### 7.1 定義

- **VIX = S&P500オプションから算出した「今後30日間の予想変動率（年率%）」**（出典: Cboe / Fidelity / Wikipedia）。満期23〜37日のSPXコール/プットの加重価格から導出。
- 「Fear Gauge（恐怖指数）」と呼ばれる。**VIX=20 は年率20%の変動を市場が織り込んでいる**ことを意味する。

### 7.2 水準の読み方（出典: Fidelity / Bankrate / whalequant）

| VIX水準 | 状態 | 例え |
|---------|------|------|
| **< 20** | 低恐怖・安定 | 「快晴」 |
| **20〜30** | 警戒・不確実性上昇 | 「暗雲」 |
| **> 30** | 重大な恐怖・大イベント発生中 | 「嵐警報」 |

### 7.3 デイトレでの使い方と落とし穴

- **使い方（地合いフィルター）**: VIXが高い＝値幅もリスクも大きい。**高VIX下では小さく張るか撤退、ストップは広げる**（出典: investing.com / tastytrade）。VIX急騰は市場ストレスのサイン＝新規回避の判断材料。
- **落とし穴①（テクニカル無力化）**: 高ボラ下では「intraday chop（日中の乱高下）、stop-hunt（ストップ狩り）、急反転」が増える。0DTEオプションのヘッジ需給が分単位で価格を振り回す（出典: investing.com）。**ストップ狩りに遭いやすく、テクニカルの精度が落ちる**。
- **落とし穴②（VIXだけでは不十分）**: 2024/8/5 のVIXは1日で+180%・寄り前ほぼ66まで急騰。ビッド・アスク拡大など**流動性・市場構造（マイクロストラクチャ）が、ファンダ材料と無関係に変動を増幅**した（出典: BIS Bulletin 95）。「VIXを読んで取引する」旧来手法は、60%超が0DTEとなった市場では更新が必要（出典: investing.com）。

---

## 8. バリュエーション指標の基礎（デイトレでの位置づけ）

| 指標 | 意味 | デイトレでの位置づけ |
|------|------|------------------|
| **PER（株価収益率, P/E）** | 株価 ÷ EPS | デイトレでは直接使わない。長期/スイングの割安判断用 |
| **PSR（株価売上高倍率, P/S）** | 時価総額 ÷ 売上 | 同上。赤字グロース株の評価に使う長期指標 |
| **PBR / EV/EBITDA 等** | 資産・キャッシュフロー基準 | デイトレ無関係 |

> **結論**: バリュエーション指標はデイトレの売買トリガーにはならない。これらが効くのは「決算でサプライズが出たとき、市場が割高/割安を再評価して動く」局面の**背景説明**としてのみ。**デイトレーダーが見るのは PER の絶対値ではなく「市場の期待（コンセンサス）に対してサプライズが出たか」**。

---

## 9. 本ボットへの紐付け（IBKR bot 専用提案）

> 現状: QQQ中心+約40銘柄 / VIX≥30 でエントリーブロック / 経済イベントゲート（FOMC/CPI/PCE前後で observe）を最近追加 / PAPER・未入金。

### 9.1 ① botが避けるべき高イベントリスク日の運用

**結論: 「予告できる日程もの」は事前にエントリーを止める/縮小するゲートを徹底すべき。**

| イベント | ボットの推奨挙動 | 根拠 |
|---------|----------------|------|
| **保有銘柄の決算当日（前後1営業日）** | その銘柄を新規エントリー対象から除外 | ギャップ+IVクラッシュ+方向不明（§2） |
| **FOMC会合2日目（声明 14:00 ET=翌3:00 JST）** | 当日エントリー停止 or 縮小（既存observeを block寄りに） | 引け間際の2段階whipsaw（§3.2） |
| **CPI/PCE/NFP発表日（8:30 ET=21:30 JST）** | 寄り後30〜60分の新規を停止 or 縮小 | 寄り前ジャンプ→寄り後が荒れる（§3.2） |

- **具体策**: 経済イベントゲートを `observe`（記録のみ）から、検証後に **発表日の寄り後一定時間 or FOMC当日の新規ブロック** へ昇格。BTC側 chop_filter の observe→block 移行と同じ運用思想。
- **決算ゲートの新設提案**: 監視40銘柄について Nasdaq Earnings / 8-K(Item 2.02) から**決算日を取得し、当日±1日はその銘柄をスキップ**するゲートを追加（現状この決算ゲートが無いなら最優先）。

### 9.2 ② VIXゲート閾値（≥30）の妥当性

**結論: VIX≥30 ブロックは「嵐警報＝重大恐怖」水準に一致し妥当。ただし 20〜30 の警戒帯は「素通し」になっている。**

- VIX>30 は「significant fear・大イベント発生中」（§7.2）であり、ブロック閾値として理にかなう。
- ただし 20〜30 は「不確実性上昇・大きめの値動きを織り込み始め」の帯。**この帯では高ベータのQQPは振れ幅が増し、ストップ狩りも増える**（§7.3）。
- **提案（2段ゲート化）**: VIX≥30=全ブロック（現状維持） / **VIX 20〜30=ポジション縮小 or ストップ拡大 or 取引数上限引き下げ**。一律閾値より滑らかにリスクを絞れる。検証は observe で件数・WRを取ってから。

### 9.3 ③ カタリスト主導日に1分足テクニカルが効かなくなる点

**結論: 決算/FOMC/指標の「瞬間ジャンプ」は1分足の連続性を断つ。テクニカル前提（MA・S/R・RSI）が無効化する。**

- ギャップは「場が閉じている間」に起き、1分足チャートに連続線が無い＝直近サポート/レジスタンスやMAが意味を失う（§2.1, §3.2）。
- 高VIX/イベント下は stop-hunt と急反転で**1分足のブレイクアウト/プルバックがダマシ化**（§7.3）。
- **ボット示唆**: ①テクニカル・シグナルの信頼度を「イベント日は減点」する重み付け（既存の chop/regime ゲート思想を流用）②イベント直後N分はテクニカル判定をスキップ ③イベント日は実効的に「テクニカルが効く通常日」だけで戦うよう新規を絞る。**カタリスト日は1分足を信じない**を明文ルール化。

### 9.4 ④ 監視銘柄選定で見るべきファンダ要素

**結論: デイトレ銘柄選定でも、最低限のファンダ＝「決算日・ベータ・流動性・セクター分散」は確認すべき。**

| 確認要素 | 見方 | 理由 |
|---------|------|------|
| **決算日程** | Nasdaq Earnings / 8-K | 決算週の銘柄は地雷。日程を持って当日除外（§9.1） |
| **ベータ（対SPY/QQQ）** | QQQベータ≈1.3が基準（§4.1） | 高ベータ＝値幅もリスクも大。ボット許容ボラと整合させる |
| **流動性（出来高・スプレッド）** | 大型・高出来高優先 | 約定・スリッページ・ストップ狩り耐性 |
| **セクター分散** | 同一セクター偏重を避ける | 1材料で全銘柄同時被弾を防ぐ（§4.2） |
| **指数連動の素直さ** | QQQ/SPYとの相関 | 個別材料に振られにくい銘柄は地合い戦略と相性良 |

- **具体策**: 監視40銘柄リストに「次回決算予定日」列を持たせ、決算週は自動で監視一時除外。半導体/AI等のセクター集中があれば上限を設けて分散。

---

## 参考ソース（URL一覧）

**経済指標・日程（一次情報）**
- Federal Reserve — FOMC calendars: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
- Federal Reserve — 2025/2026 tentative schedule: https://www.federalreserve.gov/newsevents/pressreleases/monetary20240809a.htm
- BLS — CPI schedule: https://www.bls.gov/schedule/news_release/cpi.htm
- BLS — Employment Situation (NFP) schedule: https://www.bls.gov/schedule/news_release/empsit.htm
- BLS — Selected releases 2026: https://www.bls.gov/schedule/news_release/current_year.asp
- BEA — News release schedule (PCE/GDP): https://www.bea.gov/news/schedule

**SEC開示**
- SEC EDGAR full-text search: https://efts.sec.gov/LATEST/search-index?q=
- SEC EDGAR latest filings: https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent
- SEC filing deadlines (AssetRoom): https://www.assetroom.net/sec-filing-deadlines
- 2026 SEC filing deadlines (Mayer Brown PDF): https://www.mayerbrown.com/-/media/files/perspectives-events/publications/2025/12/2026-sec-filing-deadlines-and-financial-statement-staleness-dates.pdf

**決算・PEAD・IVクラッシュ**
- Post–earnings-announcement drift (Wikipedia): https://en.wikipedia.org/wiki/Post%E2%80%93earnings-announcement_drift
- PEAD strategy (DayTrading.com): https://www.daytrading.com/post-earnings-announcement-drift-pead-strategy
- Volatility trading around earnings (TradingRiot): https://blog.tradingriot.com/p/volatility-trading-around-earnings
- Volatility crush / IV drop (Volatility Box): https://volatilitybox.com/research/volatility-crush-earnings/
- Earnings & options volatility (Collin Seow): https://collinseow.com/earnings-volatility/
- Nasdaq earnings calendar: https://www.nasdaq.com/market-activity/earnings

**VIX**
- Cboe VIX products: https://www.cboe.com/tradable-products/vix/
- What is the VIX (Fidelity): https://www.fidelity.com/learning-center/smart-money/what-is-vix
- VIX (Wikipedia): https://en.wikipedia.org/wiki/VIX
- VIX index (Bankrate): https://www.bankrate.com/investing/vix-volatility-index/
- VIX guide (WhaleQuant): https://whalequant.io/en/vix
- FRED VIXCLS history: https://fred.stlouisfed.org/series/VIXCLS/
- BIS Bulletin 95 — Aug 2024 VIX spike: https://www.bis.org/publ/bisbull95.pdf
- VIX & 0DTE warning signs (Investing.com): https://www.investing.com/analysis/3-warning-signs-the-vix-wont-tell-you-about-anymore-200668800

**指数・ベータ・セクター**
- SPY vs QQQ (Validea): https://blog.validea.com/spy-vs-qqq-battle-of-the-etf-behemoths/
- QQQ beta (macroaxis): https://www.macroaxis.com/stocks/beta/QQQ
- QQQ vs SPY comparison (stockanalysis): https://stockanalysis.com/etf/compare/qqq-vs-spy/
- SPY vs QQQ signals (bookmap): https://bookmap.com/blog/spy-vs-qqq-why-traders-watch-them-closely-and-how-to-analyze-their-market-signals

**指標の市場影響（NFP等）**
- Jobs report (Kiplinger): https://www.kiplinger.com/investing/when-is-the-next-jobs-report
- NFP release (EBC): https://www.ebc.com/forex/nonfarm-payrolls-today-release-time-and-key-signals

---

## 要点3行

1. デイトレにファンダ分析は不要だが「カタリスト把握」は必須 — 決算/FOMC(14:00ET=翌3:00JST)/CPI・PCE・NFP(8:30ET=21:30JST)は瞬間ジャンプを起こし1分足テクニカルを無力化する。
2. 一次情報は日程とVIX — SEC EDGAR(8-K Item2.02)・BLS/BEA/Fed カレンダー・Cboe VIXで「いつ荒れるか」を先に押さえる。VIX<20快晴/20-30暗雲/>30嵐警報。
3. 本ボットには①決算・FOMC・指標日の新規エントリー停止/縮小ゲート ②VIX≥30維持＋20-30縮小の2段化 ③カタリスト日は1分足を信じない明文化 ④監視銘柄に決算日程・ベータ・流動性・セクター分散の確認列を提案。
