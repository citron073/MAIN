# 01. ローソク足の読み方 — 米株デイトレ(1〜5分足)知識ベース

> 対象: IBKR bot(QQQ/個別株、1分足SMAクロス、SL -0.5% / TP +1.0%)の改善
> 作成: 2026-06-11 / 米株デイトレ(1〜5分足)特化
> 統計の原典: Thomas Bulkowski "Encyclopedia of Candlestick Charts"(thepatternsite.com・103パターン検証)

---

## 結論先出し(要点3行)

1. **ローソク足単体の勝率は「ほぼコイン投げ寄り」**。Bulkowski の検証でも最良級の反転足(morning star)で 78%、hammer/engulfing は 60〜63% にとどまる。査読論文では「単独使用では統計的に有意なリターンを生まない」が結論。→ **単体シグナルで張らない。上位足の文脈・S/R・VWAP と必ず併用**。
2. **1〜5分足はノイズ(騙し)が最多**。日足より信頼度が落ちる。デイトレでは「足の形」を**フィルター(やらない判断)**に使うのが費用対効果が高い。
3. **本botの直近7連敗デッドクロスSELLは、ローソク足で言えば「下げ切った後の反転足(long lower shadow / hammer / bullish engulfing)を空売り直前に見落とした」典型**。→ 本書末尾の「botが空売りを避けるべき足」を実装フィルター候補とする。

---

## 1. ローソク足の基本構造

1本のローソクは**ある時間枠(1分・5分など)の4つの価格**を1図形に圧縮する。

```
      ┃   ← 上ヒゲ (upper shadow / wick): 高値(High)まで
    ┏━┓  ← 実体上端
    ┃ ┃  ← 実体 (body): 始値(Open)〜終値(Close)
    ┗━┛  ← 実体下端
      ┃   ← 下ヒゲ (lower shadow): 安値(Low)まで
```

| 部位 | 意味 | 需給の読み |
|------|------|-----------|
| 実体 (body) | 始値〜終値の幅 | 大きい=その方向の圧力が強く確定。小さい=拮抗/迷い |
| 陽線(白/緑) | 終値 > 始値 | 期間中に買いが押し切った |
| 陰線(黒/赤) | 終値 < 始値 | 期間中に売りが押し切った |
| 上ヒゲ | 高値 − 実体上端 | 上で売られて押し戻された=上値の売り圧 |
| 下ヒゲ | 実体下端 − 安値 | 下で買われて押し戻された=下値の買い支え |

**読みの核心**: 終値は「その時間枠の最終決着」、ヒゲは「試したが拒否された価格帯」。**長いヒゲ = その方向への拒否(rejection)**であり、デイトレでは反転の最重要シグナル。

---

## 2. 単一足パターン(single candle)

| パターン | 形 | 需給の意味 | 出やすい場所 |
|---------|----|-----------|------------|
| Hammer(ハンマー) | 下に長いヒゲ・小実体・上ヒゲほぼ無し | 下落中に下値を買い支えた=下げ拒否 | 下降後の底 |
| Shooting star | 上に長いヒゲ・小実体・下ヒゲほぼ無し | 上昇中に上値を売られた=上げ拒否 | 上昇後の天井 |
| Inverted hammer | 上に長いヒゲ・小実体(下落中) | 上値を試したが戻された(底候補だが弱い) | 下降後の底 |
| Pin bar | 実体小・片側に長いヒゲ(hammer/star の総称) | ヒゲ方向への突入が**拒否**された | S/R・VWAP接触点 |
| Doji | 始値≒終値(十字) | 完全な拮抗・迷い。トレンド息切れ | トレンド転換前 |
| Marubozu | ヒゲ無しの大陽/大陰線 | 一方向の圧力が始値から終値まで継続 | ブレイク・トレンド継続 |

### ASCIIサンプル

```
Hammer (底・買い拒否なし=下げ拒否)     Shooting star (天井・上げ拒否)
   ┏┓                                      ┃
   ┗┛                                      ┃
    ┃                                     ┏┓
    ┃   ← 長い下ヒゲ                       ┗┛
    ┃

Doji (拮抗)        Bullish Marubozu (一方的買い)
   ┃                  ┏━┓
  ─╂─                 ┃ ┃   ← ヒゲ無し
   ┃                  ┗━┛
```

### Bulkowski 統計(原典: thepatternsite.com)

| パターン | 反転として機能する率 | 反転ランク(1=最良/103中) | 総合パフォーマンスランク | 補足 |
|---------|------------------|------------------------|---------------------|------|
| Hammer | **60%**(bullish reversal) | 26 | 65 | 下ヒゲは実体の2〜3倍以上必要。年間安値近辺・白実体で最良。「respectable だが random からそう遠くない」 |
| Inverted hammer | 実際は **bearish continuation 65%** | — | 6 | 名前と裏腹に反転より継続。**底だからと飛びつくと危険** |
| Bullish engulfing | 63%(後述・複数足) | 22 | 84 | 頻度は高い(rank 12)が反転後の伸びは弱い |

> 出典: thepatternsite.com/Hammer.html, /HammerInv.html, /BullEngulfing.html

---

## 3. 複数足パターン(multi-candle)

| パターン | 構成 | 意味 |
|---------|------|------|
| Bullish engulfing | 陰線 → それを包む大陽線 | 売りを買いが飲み込んだ=底の反転 |
| Bearish engulfing | 陽線 → それを包む大陰線 | 買いを売りが飲み込んだ=天井の反転 |
| Harami(はらみ) | 大実体 → 内側の小実体 | 勢いの急減速・トレンド一服 |
| Morning star | 大陰線 → 小実体(窓) → 大陽線 | 底での3段階反転 |
| Evening star | 大陽線 → 小実体(窓) → 大陰線 | 天井での3段階反転 |
| Three white soldiers | 連続する3本の大陽線 | 強い買い継続/底からの反転 |
| Three black crows | 連続する3本の大陰線 | 強い売り継続 |

### ASCIIサンプル

```
Bullish Engulfing (底)            Morning Star (底)
  ┏━┓                             ┏┓
  ┃ ┃ ← 大陽線が                  ┃┃ 大陰線
 ┏┛ ┗┓   前の陰線を包む           ┗┛
 ┃┏━┓┃                              ▫  ← 小実体(窓を空けて下)
 ┗┃ ┃┛                            ┏┓
   ┗━┛ ← 前の小陰線               ┃┃ 大陽線(第1陰線の半値以上戻す)
                                   ┗┛
```

### Bulkowski 統計

| パターン | 機能率 | 反転ランク | 総合ランク | 頻度ランク |
|---------|-------|----------|----------|----------|
| Bullish engulfing | 63% bullish reversal | 22 | 84 | 12(高頻度) |
| Bearish engulfing | **79% bearish reversal** | **5** | — | — |
| Morning star | **78% bullish reversal** | **6** | **12** | 66 |

> Morning star / bearish engulfing は反転ランク上位(信頼度が高い部類)。一方 hammer / bullish engulfing は機能率60%台で「弱い反転」。
> 出典: thepatternsite.com/BullEngulfing.html, /BearEngulfing.html, /MorningStar.html

---

## 4. パターンの「信頼度」エビデンス

### 4-1. Bulkowski 実測の含意
- 反転率が最も高い部類(morning star 78%, bearish engulfing 79%)でも**5本に1本は外れる**。
- 反転率と「反転後の伸び(総合ランク)」は別物。bullish engulfing は反転率63%でも総合ランク84=**当たっても伸びない**。デイトレのTP設計に直結。
- white-bodied hammer / 年間安値近辺など**文脈で機能率が変わる**=単体では確率が不安定。

### 4-2. 査読論文の含意(単独使用への警告)
- "Profitability of Candlestick Charting Patterns in the Stock Exchange of Thailand"(Tharavanij et al., 2017, SAGE Open): 多くの反転パターンは**統計的に有意な平均リターンを生まない**。有意なものも標準偏差(リスク)が非常に大きい。
- 系統的レビュー(IJRPR 2024): **時間枠が短いほど(分足)騙しが増える**。日足はノイズが減り相対的に信頼度が高い。複数指標との併用で誤シグナル確率が下がる。

### 4-3. 出来高との併用
- 反転足は**出来高を伴うとき信頼度が上がる**(拒否に実需が伴った証拠)。薄商いの長ヒゲは無視されやすい。
- デイトレでは VWAP・前日終値・寄り後の高安などの**価格レベル上で出たパターンのみ採用**するのが実務的フィルター。

---

## 5. デイトレ(1〜5分足)での使い方

### なぜ単体で使ってはいけないか
- **1〜5分足は騙し(noise)が構造的に多い**。1本のヒゲは数十秒の板の偏りで簡単に作られ、すぐ否定される。
- 反転足は「**どこで出たか**」が9割。同じ hammer でも、VWAP/前日安値/サポート上で出れば有効、無背景の途中で出れば無意味。

### 併用すべき文脈(チェックリスト)
- [ ] **上位足の方向**: 5分足のトレンドに逆らう1分足シグナルは信頼度が落ちる。
- [ ] **S/R(支持/抵抗)**: 直近高安・ラウンドナンバー・前日終値に接触しているか。
- [ ] **VWAP**: VWAP接触/反発での反転足は機能しやすい(機関の基準線)。
- [ ] **出来高**: 反転足が平均超の出来高を伴うか。
- [ ] **位置**: 「下げ切った後」か「上げ切った後」か(伸び切った所での反転足ほど効く)。

### エントリー/損切りの置き所(具体例)

```
例1: VWAP反発の Hammer で買い
  ─── VWAP ───────●  ← ここで hammer の下ヒゲがVWAPを下抜けて戻す
                  ┏┓
                  ┗┛
                   ┃ ← 下ヒゲ安値
  Entry: hammer 確定足の終値、または次足の高値ブレイク
  Stop : 下ヒゲ安値の数ティック下(ここを割れたら反転否定)
  Target: 直近レジ / R:R 1.5〜2.0

例2: レジ接触の Shooting star で売り(空売り)
  ─── 直近高値 ── ┃ ← 上ヒゲがレジを試して拒否
                 ┏┓
                 ┗┛
  Entry: shooting star 次足の安値ブレイク
  Stop : 上ヒゲ高値の上(ここを超えたら売り否定)
```

**原則**: 損切りは常に「**パターンが否定される価格**」に置く(ヒゲの先)。TPは固定%でなく直近S/Rまで。本botの TP +1.0% / SL -0.5% は固定だが、ローソク足の観点では「**ヒゲ先が -0.5% より遠いなら、その足ではエントリーしない**」という見送り基準として使える。

---

## 6. 【本IBKR botへの紐付け】botが空売りを避けるべき足

### 現状の問題
- bot ロジック: 1分足 SMA fast/slow クロス。デッドクロス=SELL(空売り)、ゴールデン=BUY。SL -0.5%(タイト)/ TP +1.0%。
- 直近の負け: **デッドクロスSELL を7連続 → 全部逆行ストップ**。
- 典型例: **AMD が日中 -2.70% 下落済みの所で SELL → +0.5% 反発でストップ**。

### ローソク足から見た敗因
SMAクロスは**遅行指標**。fast/slow がクロスした時点では「すでに下げ切った後」のことが多い。
そこは**売り方が利確し、buyの押し目買いが入る反転ゾーン**=**hammer / bullish engulfing / 長い下ヒゲ**が出やすい場所。
botはこの「下げ拒否の足」を見ずに空売りするため、**底でショートして反発(short squeeze的な戻し)でストップ**を量産している。

### botが空売り(SELL)を避けるべき足のシグナル一覧

> 「直近で大きく下落済み(例: 当日 -2% 超)」+「デッドクロス点で以下が出ている」場合、**SELLを見送る**。

| # | 足の形 | 検出条件(数値ロジック例) | 意味 |
|---|--------|------------------------|------|
| 1 | **Hammer / 長い下ヒゲ** | 下ヒゲ ≥ 実体の2倍 かつ 上ヒゲ ≤ 実体 | 下値で買い支え=下げ拒否 |
| 2 | **Bullish engulfing** | 直近陰線を包む大陽線(今足 close > 前足 open, 今足 open < 前足 close) | 売りを買いが飲み込んだ=底反転 |
| 3 | **Bullish marubozu / 連続陽線** | 直近2〜3本が陽線、ヒゲ小 | 反発の勢いが出ている(squeeze兆候) |
| 4 | **Doji(下落の底)** | |open−close| が実体レンジの極小 | 売り勢の息切れ=拮抗、SELL妙味消滅 |
| 5 | **Morning star** | 大陰線→小実体→第1陰線半値超え戻す大陽線 | 反転ランク6の強い底反転(最警戒) |
| 6 | **過伸び(over-extension)** | VWAP/移動平均からの下方乖離が大 + 出来高ピーク後 | セリングクライマックス=反発しやすい |

### 実装提案(フィルター案・要たにさん承認)
1. **SELLゲート**: デッドクロス検知時、直近Nバーで上記#1〜#5のいずれかを検出したら **その日の空売りをスキップ**(observe ログのみ)。
2. **過伸びゲート**: 「当日安値からの戻し率」または「VWAP下方乖離率」が閾値超なら SELL 見送り(AMDの -2.70% 後の事例に直撃)。
3. **段階導入**: 既存の chop_filter と同様 `observe`(記録のみ)→検証→`block` の順で。BTC側の chop_filter_mode 運用に倣う。

> いずれも CONTROL/IBKR_CONTROL のパラメータ変更・コード変更に該当 = 🟡実行前確認。本書は知識ベースであり自動適用しない。

---

## 参考ソース

- Thomas Bulkowski, Hammer 統計: https://thepatternsite.com/Hammer.html
- Thomas Bulkowski, Inverted Hammer 統計: https://thepatternsite.com/HammerInv.html
- Thomas Bulkowski, Bullish Engulfing 統計: https://thepatternsite.com/BullEngulfing.html
- Thomas Bulkowski, Bearish Engulfing 統計: https://thepatternsite.com/BearEngulfing.html
- Thomas Bulkowski, Morning Star 統計: https://thepatternsite.com/MorningStar.html
- Thomas Bulkowski, Candlestick Patterns 総覧: https://thepatternsite.com/CandleEntry.html
- Tharavanij, Siraprapasiri & Rajchamaha (2017), "Profitability of Candlestick Charting Patterns in the Stock Exchange of Thailand", SAGE Open: https://journals.sagepub.com/doi/10.1177/2158244017736799
- "Candlestick Patterns Trading Strategies: A Systematic Review", IJRPR Vol.5 Issue 5 (2024): https://ijrpr.com/uploads/V5ISSUE5/IJRPR27832.pdf
- Fidelity, "The Eight Best Candles"(Bulkowski 検証ベース): https://www.fidelity.com/bin-public/060_www_fidelity_com/documents/EightBestCandles.pdf

---

## このドキュメントの要点(1〜3行)

- ローソク足単体の反転勝率は最良級(morning star)でも78%、hammer/engulfing は60〜63%で、査読研究でも「単独使用は非有意」。**上位足・S/R・VWAP・出来高と必ず併用**する。
- 1〜5分足は騙しが最多で、ローソク足は「張る理由」より「**見送る理由(フィルター)**」に使うのが費用対効果が高い。
- 本botの7連敗デッドクロスSELLは「下げ切った後の反転足(hammer/bullish engulfing/長い下ヒゲ/morning star)を空売り直前に見落とした」典型 → §6の足シグナルでSELLゲートを observe から導入すべき。
