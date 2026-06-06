#!/usr/bin/env python3
"""Ouroboros 投資円卓会議（Investor Council）エンジン

note記事 (note.com/futsuoji_nisa/n/n1e2cb12befe7) の「11人の伝説的投資家を
円卓会議でロールプレイさせる」手法を常設化したもの。

各投資家は実在の著者の **公開された著書・哲学に基づくルールの再現（トレース）**。
本人の発言・承認ではない。詳細は MAIN/docs/INVESTOR_COUNCIL.md を参照。

設計: 既定は PASS（買わない技術）。
  1. 規律陣のいずれかが VETO → PASS
  2. ALL-YES ゲート（記事の5条件の株版）に NO → PASS
  3. 攻撃陣の重み付き conviction ≥ 閾値 → CONFIRM（発注）

ボットからは evaluate(features, ctrl) を呼ぶ。features は ibkr_bot が既に計算する
スカラ群（signal/trend/price/vwap/atr/daily_move/tp_pct/sl_pct/vix/in_universe...）。
欠損キーは中立扱い（堅牢性優先）。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_VERSION = "2026.06.03.1"

MAIN_DIR = Path(__file__).resolve().parent
REPORT_DIR = MAIN_DIR / "local_ai" / "investor_council"
REPORT_JSON = REPORT_DIR / "council_report.json"
REPORT_MD = REPORT_DIR / "council_report.md"
STATE_JSON = REPORT_DIR / "council_week_state.json"

JST = timezone(timedelta(hours=9))


# ───────────────────────── helpers ─────────────────────────
def _f(features: Dict, key: str) -> Optional[float]:
    v = features.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _aligned_vwap(signal: str, price: Optional[float], vwap: Optional[float]) -> Optional[bool]:
    """シグナル方向がVWAPの順方向側か。Noneなら判定不能。"""
    if price is None or vwap is None:
        return None
    if signal == "BUY":
        return price >= vwap
    if signal == "SELL":
        return price <= vwap
    return None


def _trend_confirms(signal: str, trend: str) -> bool:
    t = (trend or "").lower()
    if signal == "BUY":
        return t in ("up", "bull", "bullish")
    if signal == "SELL":
        return t in ("down", "bear", "bearish")
    return False


def _signed_daily_move(signal: str, daily_move: Optional[float]) -> Optional[float]:
    """ポジション方向から見た当日の値動き（順行=正）。"""
    if daily_move is None:
        return None
    return daily_move if signal == "BUY" else -daily_move


# ───────────────────────── 攻撃陣（張る判断） ─────────────────────────
def _attack_votes(features: Dict) -> List[Dict[str, Any]]:
    signal = features.get("signal", "")
    price = _f(features, "price")
    vwap = _f(features, "vwap")
    atr = _f(features, "atr")
    daily_move = _f(features, "daily_move")
    sd_move = _signed_daily_move(signal, daily_move)
    trend = features.get("trend", "")
    vwap_aligned = _aligned_vwap(signal, price, vwap)
    vol_surge = bool(features.get("volume_surge", False))
    atr_pct = (atr / price * 100) if (atr is not None and price) else None
    votes: List[Dict[str, Any]] = []

    # 1. O'Neil (CAN SLIM): 強さを買う・MA上・出来高
    on = (vwap_aligned is True) and _trend_confirms(signal, trend) and (sd_move is None or sd_move >= 0)
    votes.append({
        "name": "O'Neil", "weight": 1.2,
        "vote": 1 if on else 0,
        "reason": "強さ＋トレンド一致＋VWAP順方向" if on else "強さ条件を満たさず",
    })

    # 2. Minervini (SEPA): 上昇トレンド＋VWAP上＋ボラ収縮
    mv = _trend_confirms(signal, trend) and (vwap_aligned is True) and (atr_pct is not None and atr_pct <= 0.6)
    votes.append({
        "name": "Minervini", "weight": 1.1,
        "vote": 1 if mv else 0,
        "reason": "トレンド＋ボラ収縮ブレイク" if mv else "ボラ収縮/トレンド条件未達",
    })

    # 3. Livermore: 最小抵抗線＝トレンド確認のみ
    lv_ok = _trend_confirms(signal, trend)
    votes.append({
        "name": "Livermore", "weight": 1.1,
        "vote": 1 if lv_ok else 0,
        "reason": "最小抵抗線の方向" if lv_ok else "確認不十分",
    })

    # 4. Darvas (box): レンジ上抜け＝VWAP順方向＋出来高
    dv = (vwap_aligned is True) and vol_surge
    votes.append({
        "name": "Darvas", "weight": 0.9,
        "vote": 1 if dv else 0,
        "reason": "ボックス上抜け＋出来高" if dv else "ブレイク/出来高なし",
    })

    # 5. Druckenmiller: コンビクション増幅（他攻撃陣の賛成数に依存。集計側で加点）
    votes.append({
        "name": "Druckenmiller", "weight": 0.0,  # 集計で動的に効かせる
        "vote": 0, "reason": "確信が高い時のみ集中（集計で増幅）",
        "_amplifier": True,
    })

    # 6. Soros (reflexivity): 大きな順行モメンタム
    so = (sd_move is not None and sd_move >= 0.5)
    votes.append({
        "name": "Soros", "weight": 1.0,
        "vote": 1 if so else 0,
        "reason": "自己強化的モメンタム" if so else "モメンタム不足",
    })
    return votes


# ───────────────────────── 規律陣（拒否権） ─────────────────────────
def _discipline_review(features: Dict, ctrl: Dict) -> List[Dict[str, Any]]:
    signal = features.get("signal", "")
    trend = features.get("trend", "")
    daily_move = _f(features, "daily_move")
    sd_move = _signed_daily_move(signal, daily_move)
    tp = _f(features, "tp_pct")
    sl = _f(features, "sl_pct")
    vix = _f(features, "vix")
    in_universe = features.get("in_universe", True)
    overext = _cf(ctrl, "ibkr_council_overextended_pct", 3.0)
    vertical = _cf(ctrl, "ibkr_council_vertical_pct", 4.0)
    rr_min = _cf(ctrl, "ibkr_council_min_rr", 2.0)
    vix_max = _cf(ctrl, "ibkr_vix_block_threshold", 30.0)
    reviews: List[Dict[str, Any]] = []

    # 7. Graham: 過伸張を買わない（安全余裕）
    g_veto = sd_move is not None and sd_move > overext
    reviews.append({
        "name": "Graham", "ok": not g_veto,
        "reason": f"順行{sd_move:.2f}% > {overext}% 過伸張で安全余裕なし" if g_veto
        else "安全余裕あり",
    })

    # 8. Templeton: 垂直・放物線の急騰に飛び乗らない（陶酔回避）
    t_veto = sd_move is not None and sd_move > vertical
    reviews.append({
        "name": "Templeton", "ok": not t_veto,
        "reason": f"垂直急騰{sd_move:.2f}% > {vertical}%（陶酔）" if t_veto else "陶酔局面でない",
    })

    # 9. Lynch: 自分が分かるもの（監視ユニバース内）のみ
    l_veto = not bool(in_universe)
    reviews.append({
        "name": "Lynch", "ok": not l_veto,
        "reason": "監視ユニバース外（未知銘柄）" if l_veto else "既知の流動性銘柄",
    })

    # 10. Marks: リスク・ファースト（R:R ≥ 2）
    rr = (tp / abs(sl)) if (tp is not None and sl not in (None, 0)) else None
    m_veto = rr is not None and rr < rr_min
    reviews.append({
        "name": "Marks", "ok": not m_veto,
        "reason": f"R:R {rr:.2f} < {rr_min} 報われないリスク" if m_veto
        else (f"R:R {rr:.2f} 良好" if rr is not None else "R:R算定不能"),
    })

    # 11. Paul Tudor Jones: 守り優先
    #   「その日の方向（最小抵抗線）に逆らうな」。20分SMAラベルは超短期ノイズなので
    #   ハード拒否しない（ボットの平均回帰戦略と衝突するため）。
    #   当日の値動きがポジションに対して強く逆行している時だけ拒否。＋VIX高で縮小。
    counter_pct = _cf(ctrl, "ibkr_council_counter_trend_daily_pct", 0.8)
    vix_hot = vix is not None and vix >= vix_max
    fighting_day = sd_move is not None and sd_move <= -counter_pct
    ptj_veto = fighting_day or vix_hot
    reviews.append({
        "name": "PaulTudorJones", "ok": not ptj_veto,
        "reason": (f"当日{sd_move:.2f}% ≤ -{counter_pct}% 当日方向に逆行" if fighting_day else
                   (f"VIX {vix:.1f} ≥ {vix_max} 守り優先" if vix_hot else "守り条件クリア")),
    })
    return reviews


# ───────────────────────── ALL-YES ゲート（記事の5条件） ─────────────────────────
def _all_yes_gate(features: Dict, ctrl: Dict) -> List[Dict[str, Any]]:
    signal = features.get("signal", "")
    daily_move = _f(features, "daily_move")
    sd_move = _signed_daily_move(signal, daily_move)
    tp = _f(features, "tp_pct")
    sl = _f(features, "sl_pct")
    vix = _f(features, "vix")
    in_universe = bool(features.get("in_universe", True))
    minutes_open = _f(features, "minutes_since_open")
    rr = (tp / abs(sl)) if (tp is not None and sl not in (None, 0)) else None
    vix_max = _cf(ctrl, "ibkr_vix_block_threshold", 30.0)
    vertical = _cf(ctrl, "ibkr_council_vertical_pct", 4.0)
    open_skip_min = _cf(ctrl, "ibkr_council_open_skip_min", 15.0)
    dd_stopped = bool(features.get("week_dd_stopped", False))
    target_hit = bool(features.get("week_target_hit", False))

    g: List[Dict[str, Any]] = []
    # ① タイミング: 寄付15分回避＋放物線でない
    timing = (minutes_open is None or minutes_open >= open_skip_min) and \
             (sd_move is None or sd_move <= vertical)
    g.append({"cond": "①タイミング", "yes": timing,
              "reason": "寄付直後/垂直上げ回避OK" if timing else "寄付急騰 or 垂直上げ"})
    # ② 体感→既知ユニバース
    g.append({"cond": "②体感(既知銘柄)", "yes": in_universe,
              "reason": "監視ユニバース内" if in_universe else "未知銘柄"})
    # ③ 金額上限→週次DDストップ未発動
    g.append({"cond": "③金額上限", "yes": not dd_stopped,
              "reason": "DDストップ未発動" if not dd_stopped else "週次DDストップ発動中"})
    # ④ ルール文書化→TP/SL定義＋R:R≥2
    rules_ok = tp is not None and sl is not None and (rr is not None and rr >= _cf(ctrl, "ibkr_council_min_rr", 2.0))
    g.append({"cond": "④ルール文書化", "yes": rules_ok,
              "reason": (f"TP/SL定義済 R:R {rr:.2f}" if rr is not None else "TP/SL未定義")})
    # ⑤ 精神状態→VIX低位＋ストレッチ目標未達（達したら降りる）
    calm = (vix is None or vix < vix_max) and not target_hit
    g.append({"cond": "⑤精神状態", "yes": calm,
              "reason": ("平穏" if (vix is None or vix < vix_max) and not target_hit
                         else ("週次目標達成→降りる" if target_hit else f"VIX {vix} 高"))})
    return g


def _cf(ctrl: Dict, key: str, default: float) -> float:
    try:
        return float(ctrl.get(key, default))
    except (TypeError, ValueError):
        return default


# ───────────────────────── 集計 ─────────────────────────
def evaluate(features: Dict, ctrl: Optional[Dict] = None) -> Dict[str, Any]:
    """円卓会議の判定。戻り値 verdict: 'CONFIRM' | 'PASS'。"""
    ctrl = ctrl or {}
    signal = features.get("signal", "")
    min_conviction = _cf(ctrl, "ibkr_council_min_conviction", 2.5)

    attack = _attack_votes(features)
    discipline = _discipline_review(features, ctrl)
    gate = _all_yes_gate(features, ctrl)

    # コア・セットアップ（Livermore 最小抵抗線 ＋ O'Neil/Darvas 強さ＝VWAP順方向）。
    # 全期間46決済の実測で、順張り+VWAP順方向 = +$4.35 / 逆張り = -$10.54。
    # この構造的エッジを CONFIRM の必須条件にする（脆い conviction 合計に依存しない）。
    require_core = _cf(ctrl, "ibkr_council_require_core_setup", 1.0) >= 1.0
    trend_ok = _trend_confirms(signal, features.get("trend", ""))
    vwap_ok = _aligned_vwap(signal, _f(features, "price"), _f(features, "vwap"))
    core_setup = trend_ok and (vwap_ok is not False)
    core_fail = require_core and not core_setup

    # 規律陣の拒否権
    vetoes = [r for r in discipline if not r["ok"]]
    gate_fails = [c for c in gate if not c["yes"]]

    # 攻撃陣 conviction（Druckenmiller増幅器を反映）
    base_yes = sum(1 for v in attack if v.get("vote", 0) > 0 and not v.get("_amplifier"))
    conviction = sum(v["weight"] * v["vote"] for v in attack if not v.get("_amplifier"))
    # Druckenmiller: 攻撃陣の賛成が多いほど集中（増幅）
    drucken_bonus = 0.0
    if base_yes >= 3:
        drucken_bonus = 0.5 * (base_yes - 2)
        conviction += drucken_bonus
    for v in attack:
        if v.get("_amplifier"):
            v["vote"] = 1 if drucken_bonus > 0 else 0
            v["weight"] = round(drucken_bonus, 2)
            v["reason"] = (f"賛成{base_yes}人で集中＋{drucken_bonus:.1f}" if drucken_bonus > 0
                           else "確信不足で集中せず")

    if core_fail:
        verdict = "PASS"
        decision_reason = ("コア・セットアップ不成立: "
                           + ("トレンド逆行" if not trend_ok else "VWAP逆方向")
                           + "（順張り＋VWAP順方向が必須）")
    elif vetoes:
        verdict = "PASS"
        decision_reason = "規律陣の拒否権: " + ", ".join(f"{v['name']}({v['reason']})" for v in vetoes)
    elif gate_fails:
        verdict = "PASS"
        decision_reason = "ALL-YESゲート不成立: " + ", ".join(c["cond"] for c in gate_fails)
    elif conviction >= min_conviction:
        verdict = "CONFIRM"
        decision_reason = f"攻撃陣 conviction {conviction:.2f} ≥ {min_conviction}（賛成{base_yes}人）"
    else:
        verdict = "PASS"
        decision_reason = f"確信度不足 conviction {conviction:.2f} < {min_conviction}"

    return {
        "verdict": verdict,
        "signal": signal,
        "symbol": features.get("symbol", ""),
        "conviction": round(conviction, 3),
        "min_conviction": min_conviction,
        "core_setup": bool(core_setup),
        "attack_yes": base_yes,
        "decision_reason": decision_reason,
        "attack": attack,
        "discipline": discipline,
        "all_yes_gate": gate,
        "vetoes": [v["name"] for v in vetoes],
        "version": SCRIPT_VERSION,
        "ts": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
    }


# ───────────────────────── 週次ガード（DD固定／ストレッチ目標） ─────────────────────────
def _iso_week(dt: datetime) -> str:
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def update_week_pnl(realized_pnl_usd: float, now: Optional[datetime] = None) -> Dict[str, Any]:
    """実現損益を週次集計に加算し、現在の週状態を返す。"""
    now = now or datetime.now(JST)
    wk = _iso_week(now)
    state = {}
    if STATE_JSON.exists():
        try:
            state = json.loads(STATE_JSON.read_text())
        except Exception:
            state = {}
    if state.get("week") != wk:
        state = {"week": wk, "realized_pnl_usd": 0.0}
    state["realized_pnl_usd"] = round(float(state.get("realized_pnl_usd", 0.0)) + realized_pnl_usd, 4)
    state["updated"] = now.strftime("%Y-%m-%d %H:%M:%S")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    STATE_JSON.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    return state


def week_guard(ctrl: Dict, now: Optional[datetime] = None) -> Dict[str, Any]:
    """週次DDストップ／ストレッチ目標の状態を返す。features に流し込む。"""
    now = now or datetime.now(JST)
    wk = _iso_week(now)
    pnl = 0.0
    if STATE_JSON.exists():
        try:
            st = json.loads(STATE_JSON.read_text())
            if st.get("week") == wk:
                pnl = float(st.get("realized_pnl_usd", 0.0))
        except Exception:
            pass
    dd_stop = _cf(ctrl, "ibkr_council_weekly_dd_stop_usd", -12.0)
    target = _cf(ctrl, "ibkr_council_weekly_target_usd", 0.0)
    dd_stopped = pnl <= dd_stop
    target_hit = target > 0 and pnl >= target
    return {
        "week": wk,
        "week_realized_pnl_usd": round(pnl, 2),
        "week_dd_stopped": dd_stopped,
        "week_target_hit": target_hit,
        "dd_stop_usd": dd_stop,
        "target_usd": target,
    }


# ───────────────────────── レポート出力 ─────────────────────────
def write_report(result: Dict[str, Any], week: Optional[Dict] = None) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(result)
    if week:
        payload["week_guard"] = week
    REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    lines = [
        f"# 投資円卓会議 議事録",
        f"- 銘柄: **{result.get('symbol','?')}**  シグナル: **{result.get('signal','?')}**",
        f"- 判定: **{result['verdict']}**  — {result['decision_reason']}",
        f"- conviction: {result['conviction']} / 閾値 {result['min_conviction']}  （攻撃賛成 {result['attack_yes']}人）",
        "",
        "## 攻撃陣",
    ]
    for v in result["attack"]:
        mark = "○" if v.get("vote", 0) > 0 else "×"
        lines.append(f"- {mark} **{v['name']}** (w={v['weight']}): {v['reason']}")
    lines.append("\n## 規律陣（拒否権）")
    for r in result["discipline"]:
        mark = "YES" if r["ok"] else "**VETO**"
        lines.append(f"- {mark} **{r['name']}**: {r['reason']}")
    lines.append("\n## ALL-YES ゲート（記事の5条件）")
    for c in result["all_yes_gate"]:
        mark = "YES" if c["yes"] else "**NO**"
        lines.append(f"- {mark} {c['cond']}: {c['reason']}")
    if week:
        lines.append("\n## 週次ガード")
        lines.append(f"- 週: {week['week']}  実現損益: ${week['week_realized_pnl_usd']:+.2f}")
        lines.append(f"- DDストップ(${week['dd_stop_usd']}): {'発動中' if week['week_dd_stopped'] else 'OK'}"
                     f" / ストレッチ目標(${week['target_usd']}): {'達成→降りる' if week['week_target_hit'] else '未達'}")
    REPORT_MD.write_text("\n".join(lines))


# ───────────────────────── 単体テスト ─────────────────────────
if __name__ == "__main__":
    # 先週の実トレードを再生して会議の判定を確認するデモ
    scenarios = [
        {"label": "GS SELL (5/30 実損 -$9.27 SL)", "f": {
            "symbol": "GS", "signal": "SELL", "trend": "up", "price": 1013.18,
            "vwap": 1010.76, "atr": 1.4536, "daily_move": 0.41, "tp_pct": 1.0,
            "sl_pct": -0.5, "vix": 15.7, "in_universe": True, "volume_surge": True}},
        {"label": "MSFT BUY (6/1→6/2 実損 -$9.19 overnight)", "f": {
            "symbol": "MSFT", "signal": "BUY", "trend": "down", "price": 461.77,
            "vwap": 462.79, "atr": 1.0421, "daily_move": -0.67, "tp_pct": 1.0,
            "sl_pct": -0.5, "vix": 16.0, "in_universe": True, "volume_surge": False}},
        {"label": "META SELL (6/1 実益 +$7.27 TP)", "f": {
            "symbol": "META", "signal": "SELL", "trend": "down", "price": 619.63,
            "vwap": 622.78, "atr": 1.8793, "daily_move": -1.48, "tp_pct": 1.0,
            "sl_pct": -0.5, "vix": 16.2, "in_universe": True, "volume_surge": True}},
        {"label": "AMD BUY (5/27 実益 +$6.29 TP)", "f": {
            "symbol": "AMD", "signal": "BUY", "trend": "up", "price": 496.15,
            "vwap": 490.37, "atr": 0.7914, "daily_move": 2.36, "tp_pct": 1.0,
            "sl_pct": -0.5, "vix": 17.1, "in_universe": True, "volume_surge": True}},
    ]
    ctrl = {"ibkr_council_min_conviction": 2.5, "ibkr_council_min_rr": 2.0,
            "ibkr_vix_block_threshold": 30.0}
    for s in scenarios:
        r = evaluate(s["f"], ctrl)
        print(f"\n=== {s['label']} ===")
        print(f"  判定: {r['verdict']}  conviction={r['conviction']} 賛成{r['attack_yes']}人")
        print(f"  理由: {r['decision_reason']}")
