# paper_sl_tp.py
import sys
import csv
import math
from datetime import datetime
from pathlib import Path
import argparse

DEFAULT_TP_PCT = 0.155   # +0.155%
DEFAULT_SL_PCT = -0.222  # -0.222%

def get_logs_dir() -> Path:
    here = Path(__file__).resolve().parent
    candidate = here.parent / "logs"
    return candidate if candidate.exists() else Path(".")

def pick_latest_trade_log(logs_dir: Path) -> Path:
    files = sorted(logs_dir.glob("trade_log_*.csv"))
    if not files:
        raise FileNotFoundError(f"{logs_dir}/trade_log_*.csv が見つかりません")
    return files[-1]

def to_float(x):
    try:
        return float(x)
    except Exception:
        return None

def read_rows(p: Path):
    with open(p, newline="") as f:
        return list(csv.DictReader(f))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path", nargs="?", help="例: ../logs/trade_log_20260127.csv")
    ap.add_argument("--tp", type=float, default=DEFAULT_TP_PCT, help="TP(%). 例: 0.155")
    ap.add_argument("--sl", type=float, default=DEFAULT_SL_PCT, help="SL(%). 例: -0.222")
    args = ap.parse_args()

    logs_dir = get_logs_dir()

    if args.csv_path:
        csv_path = Path(args.csv_path)
        if not csv_path.exists():
            raise FileNotFoundError(f"{csv_path} が見つかりません")
    else:
        csv_path = pick_latest_trade_log(logs_dir)

    rows = read_rows(csv_path)
    day_str = csv_path.stem.replace("trade_log_", "")

    papers = []
    for r in rows:
        if (r.get("result") or "") != "PAPER":
            continue
        t = r.get("time")
        entry = to_float(r.get("price"))
        side = (r.get("side") or "").upper()  # BUY/SELL が入っている想定（無ければ空）
        if (t is None) or (entry is None):
            continue
        papers.append({"time": t, "entry": entry, "side": side})

    print(f"[INFO] file: {csv_path}")
    print(f"[INFO] PAPER件数: {len(papers)}")
    print(f"[INFO] TP={args.tp:.3f}%  SL={args.sl:.3f}%")

    # 詳細CSV（logsに保存）
    detail_path = logs_dir / f"sl_tp_detail_{day_str}.csv"
    logs_dir.mkdir(parents=True, exist_ok=True)

    detail_rows = []
    for i, p in enumerate(papers, 1):
        entry = p["entry"]
        side = p["side"] if p["side"] else "BUY"  # 無い場合はBUY扱い（※確定情報ではない）
        tp_pct = args.tp / 100.0
        sl_pct = args.sl / 100.0

        if side == "BUY":
            tp_price = entry * (1.0 + tp_pct)
            sl_price = entry * (1.0 + sl_pct)
        else:  # SELL
            # SELLは価格が下がると利確、上がると損切り
            tp_price = entry * (1.0 - tp_pct)
            sl_price = entry * (1.0 - sl_pct)

        detail_rows.append({
            "day": day_str,
            "idx": i,
            "time_jst": p["time"],
            "side": side,
            "entry_price": round(entry, 1),
            "tp_pct": round(args.tp, 3),
            "sl_pct": round(args.sl, 3),
            "tp_price": round(tp_price, 1),
            "sl_price": round(sl_price, 1),
        })

    with open(detail_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(detail_rows[0].keys()) if detail_rows else [
            "day","idx","time_jst","side","entry_price","tp_pct","sl_pct","tp_price","sl_price"
        ])
        w.writeheader()
        for r in detail_rows:
            w.writerow(r)

    print(f"[INFO] saved: {detail_path}")

    # 画面にも先頭だけ表示
    for r in detail_rows[:5]:
        print(r)

if __name__ == "__main__":
    main()
