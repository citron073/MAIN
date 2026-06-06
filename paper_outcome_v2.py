#!/usr/bin/env python3
# paper_outcome_v2.py
# ------------------------------------------------------------
# 網羅版（pos_id対応 + outcome(v2)拡張）
#
# 目的:
# - trade_log_YYYYMMDD*.csv の PAPER 行ごとに、entry_time から WINDOW 分の LTP を追跡
# - TP / SL の「先に到達した方」を outcome として判定（BUY / SELL 両対応）
# - どちらも到達しなければ TIMEOUT
# - TIMEOUT 時:
#     * window 内 max/min LTP
#     * TP まで残り %（TP 幅基準で BUY/SELL 統一）
#
# 仕様（優先順位）:
# - TP:
#     1) note 内の tp_pct=
#     2) CLI --tp_buy / --tp_sell
#     3) CLI --tp（互換）
#     4) DEFAULT_BUY_TP_PCT / DEFAULT_SELL_TP_PCT
# - SL:
#     * CLI --sl（必須）
#
# pos_id:
# - note 内 pos_id= を最優先
# - 無い場合は MISSING_POS_ID_YYYYMMDD_xxx を自動付与
#
# daily_report.py との連携:
# - --tp / --sl / --win を daily_report → paper_outcome_v2 にそのまま渡せる
# - 出力ファイルは tpMIX 命名（TPがposごとに変わるため）
#
# 標準ライブラリのみ
# ------------------------------------------------------------

import argparse
import csv
import re
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter
from typing import Optional, Tuple, List, Dict

TIME_FMT = "%Y-%m-%d %H:%M:%S"

# デフォルトTP（note / CLI に無い場合）
DEFAULT_BUY_TP_PCT = 0.155
DEFAULT_SELL_TP_PCT = 0.180

STATE_FILE = Path("state.json")


# =====================
# 基本ユーティリティ
# =====================
def to_float(x) -> Optional[float]:
    try:
        if x is None:
            return None
        s = str(x).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def safe_int(x, default=None):
    try:
        if x is None:
            return default
        return int(float(str(x).strip()))
    except Exception:
        return default


def parse_time(s: str) -> Optional[datetime]:
    try:
        ss = (s or "").strip()
        if not ss:
            return None
        return datetime.strptime(ss, TIME_FMT)
    except Exception:
        return None


def safe_slug(x: float) -> str:
    s = f"{x:.6f}"
    return s.rstrip("0").rstrip(".")


def read_rows(csv_path: Path) -> List[Dict[str, str]]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# =====================
# パス解決
# =====================
def get_logs_dir() -> Path:
    here = Path(__file__).resolve().parent
    cands = [
        here.parent / "logs",
        here / "logs",
        Path("../logs").resolve(),
        Path("./logs").resolve(),
        Path(".").resolve(),
    ]
    for p in cands:
        try:
            if p.exists() and any(p.glob("trade_log_*.csv")):
                return p
        except Exception:
            pass
    return here.parent / "logs"


def pick_trade_log(logs_dir: Path, day: Optional[str]) -> Path:
    if day:
        exact = logs_dir / f"trade_log_{day}.csv"
        if exact.exists():
            return exact
        cands = sorted(logs_dir.glob(f"trade_log_{day}_*.csv"))
        if cands:
            return cands[-1]
        raise FileNotFoundError(f"trade_log_{day}*.csv が見つかりません")

    files = sorted(logs_dir.glob("trade_log_*.csv"))
    if not files:
        raise FileNotFoundError("trade_log_*.csv が見つかりません")
    return files[-1]


# =====================
# TP / SL 計算
# =====================
def price_from_pct(entry: float, pct: float) -> float:
    return entry * (1.0 + pct / 100.0)


def calc_tp_sl_prices(side: str, entry: float, tp_pct: float, sl_pct: float) -> Tuple[float, float]:
    side_u = (side or "BUY").upper()
    if side_u == "BUY":
        tp_price = price_from_pct(entry, tp_pct)
        sl_price = price_from_pct(entry, sl_pct)
    else:
        tp_price = entry * (1.0 - tp_pct / 100.0)
        sl_price = entry * (1.0 - sl_pct / 100.0)
    return tp_price, sl_price


# =====================
# outcome 判定
# =====================
def detect_outcome(side: str, times, ltps, tp_price, sl_price):
    side_u = (side or "BUY").upper()
    for t, ltp in zip(times, ltps):
        if side_u == "BUY":
            if ltp >= tp_price:
                return "TP", t, ltp
            if ltp <= sl_price:
                return "SL", t, ltp
        else:
            if ltp <= tp_price:
                return "TP", t, ltp
            if ltp >= sl_price:
                return "SL", t, ltp
    return "TIMEOUT", None, None


def tp_remaining_pct_tpwidth(side: str, entry, tp_price, wmax, wmin):
    side_u = (side or "BUY").upper()
    if side_u == "BUY":
        if wmax is None:
            return None
        tp_dist = tp_price - entry
        remain = tp_price - wmax
    else:
        if wmin is None:
            return None
        tp_dist = entry - tp_price
        remain = wmin - tp_price

    if tp_dist <= 0:
        return None
    remain = max(0.0, remain)
    return min(100.0, (remain / tp_dist) * 100.0)


# =====================
# note 解析
# =====================
def extract_tp_pct_from_note(note: str) -> Optional[float]:
    if not note:
        return None
    m = re.search(r"tp_pct\s*=\s*([-+]?\d+(?:\.\d+)?)", note)
    return to_float(m.group(1)) if m else None


def extract_pos_id_from_note(note: str) -> str:
    if not note:
        return ""
    m = re.search(r"pos_id\s*=\s*([^\s;,]+)", note)
    return m.group(1).strip() if m else ""


def pick_tp_pct(side, note, arg_tp, arg_tp_buy, arg_tp_sell):
    side_u = (side or "BUY").upper()

    tp_note = extract_tp_pct_from_note(note)
    if tp_note is not None:
        return tp_note

    if side_u == "BUY" and arg_tp_buy is not None:
        return arg_tp_buy
    if side_u == "SELL" and arg_tp_sell is not None:
        return arg_tp_sell

    if arg_tp is not None:
        return arg_tp

    return DEFAULT_BUY_TP_PCT if side_u == "BUY" else DEFAULT_SELL_TP_PCT


# =====================
# pos_id フォールバック
# =====================
def build_fallback_pos_id(day_str: str, idx: int) -> str:
    return f"MISSING_POS_ID_{day_str}_{idx:03d}"


# =====================
# メイン
# =====================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path", nargs="?", default=None)
    ap.add_argument("--day", default=None)

    # TP 系
    ap.add_argument("--tp", type=float, default=None, help="互換用TP(%)")
    ap.add_argument("--tp_buy", type=float, default=None, help="BUY用TP(%)")
    ap.add_argument("--tp_sell", type=float, default=None, help="SELL用TP(%)")

    ap.add_argument("--sl", type=float, required=True, help="SL(%)")
    ap.add_argument("--win", type=int, default=60)

    args = ap.parse_args()

    logs_dir = get_logs_dir()

    if args.csv_path:
        csv_path = Path(args.csv_path)
    else:
        csv_path = pick_trade_log(logs_dir, args.day)

    day_str = csv_path.stem.replace("trade_log_", "")
    rows = read_rows(csv_path)

    parsed = []
    for r in rows:
        t = parse_time(r.get("time"))
        if t:
            parsed.append((t, r))
    parsed.sort(key=lambda x: x[0])

    papers = []
    for t, r in parsed:
        if (r.get("result") or "").upper() == "PAPER":
            entry = to_float(r.get("price"))
            if entry is None:
                continue
            note = (r.get("note") or "")
            pos_id = extract_pos_id_from_note(note)
            side = (r.get("side") or "BUY").upper()
            papers.append((t, entry, side, note, pos_id))

    print(f"[INFO] file={csv_path} PAPER={len(papers)}")
    print(f"[INFO] SL={args.sl}% WIN={args.win}min")

    out_name = f"paper_outcome_v2_{day_str}_tpMIX_sl{safe_slug(args.sl)}_win{args.win}.csv"
    out_path = logs_dir / out_name

    results = []

    for idx, (t0, entry, side, note, pos_id) in enumerate(papers, 1):
        end = t0 + timedelta(minutes=args.win)

        times, ltps = [], []
        for t, r in parsed:
            if t < t0:
                continue
            if t > end:
                break
            ltp = to_float(r.get("ltp"))
            if ltp is not None:
                times.append(t)
                ltps.append(ltp)

        pos_id_missing = False
        if not pos_id:
            pos_id = build_fallback_pos_id(day_str, idx)
            pos_id_missing = True

        tp_pct = pick_tp_pct(side, note, args.tp, args.tp_buy, args.tp_sell)
        sl_pct = args.sl

        tp_price, sl_price = calc_tp_sl_prices(side, entry, tp_pct, sl_pct)

        wmax = max(ltps) if ltps else None
        wmin = min(ltps) if ltps else None

        if not ltps:
            outcome = "NO_DATA"
            hit_t = None
            hit_ltp = None
            tp_remain = None
        else:
            outcome, hit_t, hit_ltp = detect_outcome(side, times, ltps, tp_price, sl_price)
            tp_remain = (
                0.0 if outcome != "TIMEOUT"
                else tp_remaining_pct_tpwidth(side, entry, tp_price, wmax, wmin)
            )

        results.append({
            "pos_id": pos_id,
            "pos_id_missing": "1" if pos_id_missing else "0",
            "day": day_str,
            "idx": idx,
            "entry_time_jst": t0.strftime(TIME_FMT),
            "side": side,
            "entry_price": entry,
            "tp_pct_used": tp_pct,
            "sl_pct_used": sl_pct,
            "tp_price": round(tp_price, 1),
            "sl_price": round(sl_price, 1),
            "window_min": args.win,
            "samples": len(ltps),
            "outcome": outcome,
            "hit_time_jst": hit_t.strftime(TIME_FMT) if hit_t else "",
            "hit_ltp": round(hit_ltp, 1) if hit_ltp else "",
            "window_max_ltp": round(wmax, 1) if wmax else "",
            "window_min_ltp": round(wmin, 1) if wmin else "",
            "tp_remaining_pct": round(tp_remain, 4) if tp_remain is not None else "",
            "note": note,
        })

    cnt = Counter(r["outcome"] for r in results)
    print("[INFO] outcome summary:", dict(cnt))

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)

    print(f"[INFO] saved: {out_path}")


if __name__ == "__main__":
    main()
