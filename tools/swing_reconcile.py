#!/usr/bin/env python3
"""Phase B 実績照合ツール = 入金ゲート判定器（SWING_BOT_DESIGN.md Phase B）。

swing_bot.py の PAPER実績(swing_trade_log.csv) を集計し、バックテスト期待値(検証8-10)と照合して
GREEN/YELLOW/RED/INSUFFICIENT を機械判定する。感情を排した入金GO/NOゲート。

判定（コスト控除後ネット・等ウェイト%）:
  INSUFFICIENT : 確定トレード < MIN_TRADES → まだ判断不能(進捗を表示)
  RED          : 平均ネット期待値 < 0 (負け) → 入金しない
  YELLOW       : 0 ≤ 期待値 < FLOOR、または最大連敗がバックテスト上限を超過 → 据え置き継続
  GREEN        : 期待値 ≥ FLOOR かつ サンプル十分 かつ 連敗が想定内 → 入金検討OK

注意: あくまで「バックテスト期待レンジ内か」の整合チェック。利益保証ではない。最終判断は人間(領域1)。
"""
from __future__ import annotations

import csv
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List

MAIN_DIR = Path(__file__).resolve().parent.parent
LOG_FILE = MAIN_DIR.parent / "logs" / "swing_trade_log.csv"
CONTROL_FILE = MAIN_DIR / "SWING_CONTROL.csv"
OUT_FILE = MAIN_DIR / "review_out" / "swing_reconcile_latest.json"
SECRETS_FILE = MAIN_DIR / ".streamlit" / "secrets.toml"
JST = timezone(timedelta(hours=9))

# バックテスト期待値(検証8-10・コスト0.1%込みネット期待値%/trade)。照合の基準レンジ。
BT_EXPECTED = {
    "BTC": 1.73, "ETH": 0.36, "QQQ": 0.45, "SPY": 0.45,
    "GLD": 0.55, "MSFT": 0.62, "NVDA": 7.65, "SMH": 0.73, "NFLX": 1.51,
}
BT_MAX_STREAK = 12   # 検証9/10で観測された最大連敗の上限(US55/20で12)
PORTFOLIO_FLOOR = 0.5  # ポートフォリオ平均ネット期待値の合格下限(%/trade・保守)
MIN_TRADES = 20        # この本数未満は判断不能
DEFAULT_COST_PCT = 0.1 # 往復コスト想定(バックテストと同条件)


def _now_jst() -> datetime:
    return datetime.now(JST)


def _load_control() -> Dict[str, str]:
    ctrl: Dict[str, str] = {}
    if CONTROL_FILE.exists():
        for row in csv.reader(CONTROL_FILE.open()):
            if len(row) >= 2 and row[0].strip() and not row[0].startswith("#"):
                ctrl[row[0].strip()] = row[1].strip()
    return ctrl


def _read_secret(key: str) -> str:
    if not SECRETS_FILE.exists():
        return ""
    for line in SECRETS_FILE.read_text().splitlines():
        if line.strip().startswith(key):
            p = line.split("=", 1)
            if len(p) == 2:
                return p[1].strip().strip('"').strip("'")
    return ""


def _send_ntfy(title: str, body: str) -> None:
    url = _read_secret("ntfy_topic_url")
    st = title.encode("ascii", errors="replace").decode("ascii")
    if not url:
        print(f"[reconcile] NTFY_SKIP {st}")
        return
    try:
        req = urllib.request.Request(url, data=body.encode("utf-8"), method="POST",
                                     headers={"Content-Type": "text/plain; charset=utf-8",
                                              "Title": st, "Priority": "default", "Tags": "bar_chart"})
        with urllib.request.urlopen(req, timeout=10.0) as r:
            print(f"[reconcile] NTFY_OK http={getattr(r,'status','?')} {st}")
    except Exception as e:
        print(f"[reconcile] NTFY_FAIL {st} err={type(e).__name__}: {e}")


def _load_closed_trades(cost_pct: float) -> List[Dict[str, Any]]:
    """PAPER_EXIT 行から確定トレードを抽出( retはgross→costを引いてnet)。"""
    if not LOG_FILE.exists():
        return []
    out = []
    for row in csv.DictReader(LOG_FILE.open()):
        if row.get("event") != "PAPER_EXIT":
            continue
        m = re.search(r"ret=([+-]?[\d.]+)%", row.get("note", ""))
        if not m:
            continue
        net = float(m.group(1)) - cost_pct
        out.append({"time": row.get("time", ""), "market": row.get("market", "?"),
                    "side": row.get("side", "?"), "ret_net": round(net, 4)})
    return out


def _risk(seq: List[float]) -> Dict[str, Any]:
    cum = peak = max_dd = 0.0
    streak = max_streak = 0
    for r in seq:
        cum += r
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
        streak = streak + 1 if r <= 0 else 0
        max_streak = max(max_streak, streak)
    return {"cum": round(cum, 3), "max_dd": round(max_dd, 3), "max_streak": max_streak}


def main() -> int:
    ctrl = _load_control()
    cost = float(ctrl.get("swing_cost_pct", DEFAULT_COST_PCT))
    floor = float(ctrl.get("swing_floor_pct", PORTFOLIO_FLOOR))
    min_n = int(float(ctrl.get("swing_min_trades", MIN_TRADES)))

    trades = _load_closed_trades(cost)
    n = len(trades)
    rets = [t["ret_net"] for t in trades]
    risk = _risk(rets)
    exp = round(mean(rets), 4) if rets else 0.0
    wr = round(sum(1 for r in rets if r > 0) / n * 100, 1) if n else 0.0

    # per-market 照合
    per_market = {}
    for t in trades:
        per_market.setdefault(t["market"], []).append(t["ret_net"])
    market_rows = []
    for mk, rs in sorted(per_market.items()):
        market_rows.append({"market": mk, "n": len(rs), "exp": round(mean(rs), 3),
                            "bt_expected": BT_EXPECTED.get(mk, None)})

    # 判定
    if n < min_n:
        verdict = "INSUFFICIENT"
        reason = f"確定トレード {n}/{min_n}件。判断不能(あと{min_n - n}件)"
    elif exp < 0:
        verdict = "RED"
        reason = f"平均ネット期待値 {exp:+.3f}%/t が負け。入金しない"
    elif risk["max_streak"] > BT_MAX_STREAK:
        verdict = "YELLOW"
        reason = f"期待値+だが最大連敗 {risk['max_streak']} がBT上限{BT_MAX_STREAK}超。据え置き継続"
    elif exp >= floor:
        verdict = "GREEN"
        reason = f"期待値 {exp:+.3f}%/t ≥ 下限{floor}・サンプル十分・連敗想定内。入金検討OK"
    else:
        verdict = "YELLOW"
        reason = f"期待値 {exp:+.3f}%/t は + だが下限{floor}未満。据え置き継続"

    report = {
        "generated_at": _now_jst().strftime("%Y-%m-%d %H:%M:%S"),
        "verdict": verdict, "reason": reason,
        "closed_trades": n, "win_rate": wr, "net_exp_pct_per_trade": exp,
        "cum_net_pct": risk["cum"], "max_dd_pct": risk["max_dd"], "max_streak": risk["max_streak"],
        "cost_pct_assumed": cost, "floor_pct": floor, "min_trades": min_n,
        "per_market": market_rows,
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=1))

    icon = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴", "INSUFFICIENT": "⏳"}[verdict]
    print(f"[reconcile] {icon} {verdict}: {reason}")
    print(f"[reconcile] n={n} WR={wr}% net_exp={exp:+.3f}%/t cum={risk['cum']:+.2f}% "
          f"maxDD={risk['max_dd']:.2f}% maxStreak={risk['max_streak']}")
    body = (f"{icon} 入金ゲート: {verdict}\n{reason}\n"
            f"確定{n}件 WR{wr}% 期待値{exp:+.3f}%/t\n累計{risk['cum']:+.2f}% maxDD{risk['max_dd']:.2f}%")
    _send_ntfy(f"[SWING] 照合 {verdict}", body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
