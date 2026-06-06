# IBKR米株デイトレセットアップ実装計画

> 開始日: 2026-05-08  
> 対象: ibkr_bot.py エントリーシグナル強化  
> 進行: 段階的・PAPER検証→本番へ  
> 目的: 米株デイトレの5系統ロジックを段階導入し、SMA単純クロス→マルチセットアップ化

---

## 全体ロードマップ

| Phase | セットアップ | 優先度 | 実装状態 | テスト期間 |
|-------|-----------|--------|---------|----------|
| **1** | ② Opening Range Breakout | 🔴 最高 | □ 未 | 1–2週間 |
| **2** | ③ Dip and Rip | 🟡 高 | □ 未 | 1–2週間 |
| **3** | ⑤ Intraday VCP | 🟡 高 | □ 未 | 1–2週間 |
| **4** | ① Momentum Breakout | 🟠 中 | □ 未 | 1–2週間 |
| **5** | ④ Penny Short | 🔵 低 | □ 未 | 保留 |

**進行ルール:**
- 各Phaseは PAPER モードで ≥5営業日の実績確認後、次へ進む
- 各セットアップの WR ≥ 40% が進級条件（参考値）
- エラーや重大な問題があれば即ロールバック

---

## Phase 1: Opening Range Breakout (ORB)

### セットアップ詳細

```
【定義】
- 寄り付き後 15 分間のハイロー（Opening Range）を計算
- その範囲を上/下抜けたら、寄り付きの需給バランスが破れたシグナル
- ブレイク時に出来高増加 + VWAP上 → エントリー

【材料】
- 当日材料あり（決算・ニュース・FDA等）
- 出来高：平均以上
- ボラ：あり

【エントリー条件】
1. 寄り付き 9:30 EST から 15分間の高値(orb_high) 低値(orb_low) を記録
2. 9:45 以降、orb_high を上抜け + VWAP上 → ロング
3. 9:45 以降、orb_low を下抜け + VWAP下 → ショート
4. ブレイク足の出来高 > 直近5本平均出来高 × 1.5倍

【SL】
- ORBレンジ内へ戻る、または
- ブレイク足の安値割れ、または
- VWAP割れ

【TP】
- レンジ幅の 1倍（Measured Move）
- VWAP上での抵抗
- 前日高値・プレマーケット高値

【リスク】
- ブレイク直後のレンジ戻り（最頻パターン）→ 高速SL必須
```

### 実装内容

**A. IBKR_CONTROL.csv に追加**
```
ibkr_setup_orb_enabled,1
ibkr_setup_orb_lookback_min,15
ibkr_setup_orb_volume_threshold,1.5
ibkr_setup_orb_use_vwap,1
```

**B. ibkr_bot.py に追加関数**
```python
def _calc_opening_range(bars: List[Dict], lookback_min: int = 15) -> Tuple[float, float]:
    """寄り付き15分間のORB計算"""
    # 9:30 EST のバーから lookback_min 分間のHIGH/LOW
    
def _check_orb_breakout(
    bars: List[Dict], 
    orb_high: float, 
    orb_low: float,
    vwap: float,
    volume_threshold: float
) -> Optional[str]:
    """ORB上抜け/下抜けチェック. ロング/ショート/なし を返す"""
    # 直近足がorb_high/orb_lowを抜けたか確認
    # 出来高チェック + VWAP位置チェック
```

**C. 検出タイミング**
```
現在: SMA signal を常時計算
追加: 9:45 ET 以降で毎分 ORB breakout をチェック
優先度: ORB_SIGNAL > SMA_SIGNAL（ORB有効時）
```

### テスト項目（PAPER期間）

- [ ] ORB ハイロー正確に計算されるか（VM ログ確認）
- [ ] 出来高フィルタが適切か（リグ防止）
- [ ] VWAP 位置判定が正確か
- [ ] 実績: ≥5営業日、WR≥40% なら Phase 2 へ
- [ ] ダッシュボードに「ORB」ラベルが表示されるか

---

## Phase 2: Dip and Rip

### セットアップ詳細

```
【定義】
- ギャップアップした銘柄（決算・材料好材料）
- 寄り付き後に利確売りで一度押す
- 押し目（VWAP/9EMA付近）で買い直される
- 高値方向へ再上昇するところをロング

【材料】
- 前日・プレ市場で決算/ニュース/大型ニュース
- ギャップアップ幅：通常の出来高なら 2–5%

【エントリー条件】
1. 当日始値 > 前日終値 + gap_threshold (e.g. 1.5%)
2. 寄り付き後に VWAP まで押す（利確売り吸収）
3. 5分足で陽線包み＆反発 → エントリー
4. 直近戻り高値を抜ける
```

### 実装内容

**A. IBKR_CONTROL.csv に追加**
```
ibkr_setup_dip_rip_enabled,1
ibkr_setup_dip_rip_gap_threshold,1.5
ibkr_setup_dip_rip_vwap_retrace_pct,2.0
ibkr_setup_dip_rip_ema9,1
```

**B. ibkr_bot.py に追加関数**
```python
def _check_gap_up(prev_close: float, current_open: float, threshold_pct: float) -> bool:
    """前日終値からのギャップアップ判定"""

def _check_vwap_reversal(bars: List[Dict], vwap: float) -> Tuple[bool, float]:
    """VWAP付近での反発確認 → (反発したか, 反発価格)"""

def _check_dip_rip_setup(bars: List[Dict], vwap: float) -> Optional[str]:
    """Dip and Rip セットアップ検出"""
```

### テスト項目（PAPER期間）

- [ ] ギャップアップ検出が正確か
- [ ] VWAP 反発ロジックが信頼できるか
- [ ] 実績: ≥5営業日、WR≥40% なら Phase 3 へ

---

## Phase 3: Intraday VCP

### セットアップ詳細

```
【定義】
- 初動で強い上昇
- 利確売りで一度横ばい（高値圏）
- 押し幅が段階的に縮小（1期目 3%, 2期目 1.8%, 3期目 0.8%）
- 出来高も縮小 → 売り圧が弱い
- 最後に出来高付き上抜け

【エントリー条件】
1. 直近の上昇で ≥2% の値幅確認
2. その後、高値圏で段階的な押し（3段階が理想）
3. 各段階で出来高減少
4. 最後の段階からの上抜け + 出来高増
```

### 実装内容

**A. IBKR_CONTROL.csv に追加**
```
ibkr_setup_vcp_enabled,1
ibkr_setup_vcp_stages,3
ibkr_setup_vcp_min_initial_move,2.0
ibkr_setup_vcp_contraction_ratio,0.6
```

**B. ibkr_bot.py に追加関数**
```python
def _detect_vcp_compression(bars: List[Dict], stages: int = 3) -> Tuple[bool, Dict]:
    """VCP圧縮パターン検出 → (検出したか, メタデータ)"""
    # 段階的な押し幅縮小 + 出来高減少
    
def _check_vcp_breakout(bars: List[Dict], compression_data: Dict) -> bool:
    """圧縮完成後の上抜けチェック"""
```

### テスト項目（PAPER期間）

- [ ] 段階的な押し幅縮小が正確に検出されるか
- [ ] 出来高低下がノイズ除外できるか
- [ ] 実績: ≥5営業日、WR≥40% なら Phase 4 へ

---

## Phase 4: Momentum Breakout

### セットアップ詳細

```
【定義】
- 急騰小型株の高値更新
- 出来高急増 + 材料 → 群衆の追随買い
- VWAP上での高値突破 → モメンタム継続

【リスク】
- 最も攻撃的
- ハルト・約定滑り・反転リスク高
- 踏み上げリスクも高い
```

### 実装内容

**A. IBKR_CONTROL.csv に追加**
```
ibkr_setup_momentum_enabled,1
ibkr_setup_momentum_volume_surge_ratio,3.0
ibkr_setup_momentum_vwap_above,1
```

---

## Phase 5: Penny Stock Short（保留）

踏み上げリスク最高。当面スキップ。

---

## 共通 IBKR_CONTROL.csv 追加（全Phase共通）

```
# ── セットアップ全般 ──
ibkr_setup_mode,multi
ibkr_setup_primary_signal,orb
ibkr_setup_fallback_signal,sma
ibkr_setup_log_detail,1
ibkr_setup_combined_sl,1

# ── 共通条件 ──
ibkr_setup_vwap_enabled,1
ibkr_setup_volume_filter,1
ibkr_setup_min_atr_pct,0.5

# ── 実験フラグ ──
ibkr_setup_orb_enabled,1
ibkr_setup_dip_rip_enabled,0
ibkr_setup_vcp_enabled,0
ibkr_setup_momentum_enabled,0
```

---

## 検出ロジックの配置

```
ibkr_bot.py:

run_once():
  ├─ SMA signal 計算（基本）
  ├─ Setup signal 計算（新規）
  │   ├─ _check_orb_breakout()
  │   ├─ _check_dip_rip_setup()
  │   ├─ _check_vcp_breakout()
  │   └─ _check_momentum_breakout()
  ├─ Signal マージ（優先度制御）
  │   └─ Setup有効→Setup優先、無効→SMA
  └─ Entry ロジック（既存通り）
```

---

## ログ・ダッシュボード強化

### Trade log に追加カラム

```
setup_detected: "ORB" / "DIP_RIP" / "VCP" / "SMA" / "NONE"
setup_confidence: 0.0 - 1.0
setup_details: JSON（パラメータ詳細）
```

### dashboard.py IBKR 表示更新

- セットアップ別勝率表示
- 各セットアップの使用頻度
- Phase状況インジケータ

---

## 安全性チェックリスト

- [ ] 各Phase開始前に PAPER モード確認
- [ ] 実装後に `python3 -m py_compile ibkr_bot.py` で構文チェック
- [ ] `--dry-run` で1営業日テスト
- [ ] Log を ダッシュボードで監視
- [ ] 問題発生時：該当Setupを `enabled=0` で即停止
- [ ] ロールバック手順：git で 1コミット前に戻す

---

## 優先度決定根拠

| Rank | 理由 |
|------|------|
| ① ORB | 寄り付きレンジは計算簡単、ルール化しやすい、リグも少ない |
| ② Dip & Rip | 既存の「押し目買い」ロジックと親和性高い |
| ③ VCP | 値幅縮小を数値化しやすい、テク的に信頼性高い |
| ④ Momentum | 利益が大きいが、リスク・複雑度も高い |
| ⑤ Short | 踏み上げリスク最高、後回し |

---

## 成功条件（全Phase共通）

```
各Setupで：
- WR ≥ 40% で継続
- WR < 35% なら改善期間 or パラメータ調整
- WR < 30% なら該当Setup disable

全体：
- 統合後の平均WR：≥ 現在のSMA単独WR
- ドローダウン：現状以下
```
