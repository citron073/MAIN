# auto_tune_v1.py
# 目的:
# - trade_log_YYYYMMDD.csv から PAPER を抽出し、LTP時系列を使って
#   TP/SL/WIN の候補セットを総当たり評価（v1）
# - v1の評価:
#   * outcome: TP/SL/TIMEOUT（TIMEOUTは損益0扱い）
#   * expectancy_pct = (TP_rate*tp_pct) - (SL_rate*abs(sl_pct))
#   * MAE/MFE(%) の集計（entry基準）
#
# 実行例:
#   python3 auto_tune_v1.py --day 20260131
#   python3 auto_tune_v1.py ../logs/trade_log_20260131.csv
#
# 出力:
#   ../logs/auto_tune_v1_YYYYMMDD.csv （期待値順）
#
# 標準ライブラリのみ

import argparse
import csv
import re
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter
from typing import Optional, List, Dict, Tuple

TIME_FMT = "%Y-%m-%d %H:%M:%S"


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


def parse_time(s: str) -> Optional[datetime]:
    try:
        ss = (s or "").strip()
        if not ss:
            return None
        return datetime.strptime(ss, TIME_FMT)
    except Exception:
        return None


def get_logs_dir() -> Path:
    here = Path(__file__).resolve().parent
    return here.parent / "logs"


def pick_trade_log(logs_dir: Path, day: Optional[str]) -> Path:
    if day:
        p = logs_dir / f"trade_log_{day}.csv"
        if not p.exists():
            raise FileNotFoundError(f"{p} が見つかりません")
        return p
    files = sorted(logs_dir.glob("trade_log_*.csv"))
    if not files:
        raise FileNotFoundError("logs/trade_log_*.csv が見つかりません")
    return files[-1]


def read_rows(csv_path: Path) -> List[Dict[str, str]]:
    with open(csv_path, newline="") as f:
        return list(csv.DictReader(f))


def extract_pos_id_from_note(note: str) -> str:
    if not note:
        return ""
    m = re.search(r"pos_id\s*=\s*([^\s]+)", str(note))
    return m.group(1).strip() if m else ""


def calc_tp_sl_prices(side: str, entry: float, tp_pct: float, sl_pct: float) -> Tuple[float, float]:
    # pctは「%」単位
    side_u = (side or "BUY").strip().upper()
    if side_u == "BUY":
        tp = entry * (1.0 + tp_pct / 100.0)
        sl = entry * (1.0 + sl_pct / 100.0)  # sl_pctは負
    else:
        tp = entry * (1.0 - tp_pct / 100.0)  # 利益は下
        sl = entry * (1.0 - sl_pct / 100.0)  # sl_pctは負 → 上方向
    return tp, sl


def detect_outcome(side: str, times: List[datetime], ltps: List[float], tp_price: float, sl_price: float):
    side_u = (side or "BUY").strip().upper()
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


def mae_mfe_pct(side: str, entry: float, window_max: float, window_min: float) -> Tuple[float, float]:
    """
    MAE/MFEを「有利方向/不利方向」で揃える（%）
    - BUY: MFE = (max-entry)/entry*100, MAE = (min-entry)/entry*100
    - SELL: MFE = (entry-min)/entry*100, MAE = (entry-max)/entry*100
    """
    side_u = (side or "BUY").strip().upper()
    if side_u == "BUY":
        mfe = (window_max - entry) / entry * 100.0
        mae = (window_min - entry) / entry * 100.0
    else:
        mfe = (entry - window_min) / entry * 100.0
        mae = (entry - window_max) / entry * 100.0
    return mae, mfe


def frange(start: float, stop: float, step: float) -> List[float]:
    vals = []
    x = start
    # 浮動誤差吸収で少し余裕
    while x <= stop + 1e-9:
        vals.append(round(x, 6))
        x += step
    return vals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path", nargs="?", default=None)
    ap.add_argument("--day", default=None)

    # チューニング範囲（v1のデフォルト）
    ap.add_argument("--tp_buy_min", type=float, default=0.10)
    ap.add_argument("--tp_buy_max", type=float, default=0.22)
    ap.add_argument("--tp_sell_min", type=float, default=0.10)
    ap.add_argument("--tp_sell_max", type=float, default=0.26)
    ap.add_argument("--tp_step", type=float, default=0.01)

    ap.add_argument("--sl_min", type=float, default=-0.30)
    ap.add_argument("--sl_max", type=float, default=-0.15)
    ap.add_argument("--sl_step", type=float, default=0.01)

    ap.add_argument("--win_list", default="60,90,120", help="例: 60,90,120")

    args = ap.parse_args()

    logs_dir = get_logs_dir()
    csv_path = Path(args.csv_path) if args.csv_path else pick_trade_log(logs_dir, args.day)
    day_str = csv_path.stem.replace("trade_log_", "")

    rows = read_rows(csv_path)

    # 時系列化
    parsed = []
    for r in rows:
        t = parse_time(r.get("time", ""))
        if t:
            parsed.append((t, r))
    parsed.sort(key=lambda x: x[0])

    # PAPER抽出
    papers = []
    for t, r in parsed:
        res = (r.get("result") or "").strip().upper()
        if res == "PAPER":
            entry = to_float(r.get("price"))
            if entry is None:
                continue
            note = (r.get("note") or "").strip()
            pos_id = extract_pos_id_from_note(note) or f"MISSING_POS_ID_{day_str}_{len(papers)+1:03d}"
            side = (r.get("side") or "BUY").strip().upper() or "BUY"
            papers.append({"pos_id": pos_id, "time": t, "entry": entry, "side": side})

    if not papers:
        print(f"[INFO] file: {csv_path}")
        print("[INFO] PAPERが0件のためチューニング不可")
        return

    win_list = [int(x.strip()) for x in (args.win_list or "").split(",") if x.strip().isdigit()]

    tp_buy_vals = frange(args.tp_buy_min, args.tp_buy_max, args.tp_step)
    tp_sell_vals = frange(args.tp_sell_min, args.tp_sell_max, args.tp_step)
    sl_vals = frange(args.sl_min, args.sl_max, args.sl_step)

    print(f"[INFO] file: {csv_path}")
    print(f"[INFO] PAPER={len(papers)}  grid: tp_buy={len(tp_buy_vals)} tp_sell={len(tp_sell_vals)} sl={len(sl_vals)} win={len(win_list)}")

    out_path = logs_dir / f"auto_tune_v1_{day_str}.csv"

    results = []

    # グリッド総当たり
    for win in win_list:
        for sl_pct in sl_vals:
            for tp_buy in tp_buy_vals:
                for tp_sell in tp_sell_vals:

                    outcomes = []
                    maes = []
                    mfes = []

                    for p in papers:
                        start = p["time"]
                        end = start + timedelta(minutes=win)

                        times = []
                        ltps = []
                        for tt, rr in parsed:
                            if tt < start:
                                continue
                            if tt > end:
                                break
                            ltp = to_float(rr.get("ltp"))
                            if ltp is not None:
                                times.append(tt)
                                ltps.append(ltp)

                        if not ltps:
                            outcomes.append("NO_DATA")
                            continue

                        entry = p["entry"]
                        side = p["side"]
                        tp_pct = tp_buy if side == "BUY" else tp_sell
                        tp_price, sl_price = calc_tp_sl_prices(side, entry, tp_pct, sl_pct)

                        outcome, _, _ = detect_outcome(side, times, ltps, tp_price, sl_price)
                        outcomes.append(outcome)

                        wmax = max(ltps)
                        wmin = min(ltps)
                        mae, mfe = mae_mfe_pct(side, entry, wmax, wmin)
                        maes.append(mae)
                        mfes.append(mfe)

                    c = Counter(outcomes)
                    n = len(outcomes)
                    if n == 0:
                        continue

                    tp_n = c.get("TP", 0)
                    sl_n = c.get("SL", 0)
                    to_n = c.get("TIMEOUT", 0)
                    nd_n = c.get("NO_DATA", 0)

                    # v1期待値: TIMEOUTは0扱い（まずはシンプルに）
                    tp_rate = tp_n / n
                    sl_rate = sl_n / n
                    expectancy_pct = (tp_rate * ((tp_buy + tp_sell) / 2.0)) - (sl_rate * abs(sl_pct))

                    mae_avg = sum(maes) / len(maes) if maes else 0.0
                    mfe_avg = sum(mfes) / len(mfes) if mfes else 0.0

                    results.append({
                        "day": day_str,
                        "papers": n,
                        "win_min": win,
                        "tp_buy": tp_buy,
                        "tp_sell": tp_sell,
                        "sl": sl_pct,

                        "TP": tp_n,
                        "SL": sl_n,
                        "TIMEOUT": to_n,
                        "NO_DATA": nd_n,

                        "tp_rate_pct": round(tp_rate * 100.0, 2),
                        "sl_rate_pct": round(sl_rate * 100.0, 2),

                        "expectancy_pct_v1": round(expectancy_pct, 6),

                        "mae_avg_pct": round(mae_avg, 6),
                        "mfe_avg_pct": round(mfe_avg, 6),
                    })

    # 期待値順に並べる
    results.sort(key=lambda r: r["expectancy_pct_v1"], reverse=True)

    # 保存
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)

    print(f"[INFO] saved: {out_path}")
    if results:
        top = results[0]
    # TOP10を別CSVに保存（見やすさ用）
    topn = 10
    top_path = logs_dir / f"auto_tune_v1_{day_str}_TOP{topn}.csv"
    with open(top_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results[:topn])
    print(f"[INFO] saved: {top_path}")
    print("[TOP] win={win_min} tp_buy={tp_buy} tp_sell={tp_sell} sl={sl} exp={expectancy_pct_v1}% tp_rate={tp_rate_pct}% sl_rate={sl_rate_pct}%".format(**top))


if __name__ == "__main__":
    main()
