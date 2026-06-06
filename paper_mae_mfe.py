import sys
import csv
from datetime import datetime, timedelta
from pathlib import Path

# 計測窓（分）
WINDOW_MIN = 60


def pick_today_file() -> Path:
    # ① 引数指定があればそれを使う
    if len(sys.argv) >= 2:
        p = Path(sys.argv[1])
        if p.exists():
            return p
        raise FileNotFoundError(f"{p} が見つかりません")

    # ② ../logs/ から最新を拾う
    logs_dir = Path(__file__).resolve().parent.parent / "logs"
    files = sorted(logs_dir.glob("trade_log_*.csv"))
    if not files:
        raise FileNotFoundError("logs/trade_log_*.csv が見つかりません")
    return files[-1]


def parse_time_jst(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def to_float(x):
    try:
        return float(x)
    except Exception:
        return None


def read_rows(csv_path: Path):
    with open(csv_path, newline="") as f:
        return list(csv.DictReader(f))


def read_papers(rows):
    papers = []
    for row in rows:
        if (row.get("result") or "") != "PAPER":
            continue
        t = parse_time_jst(row.get("time", ""))
        entry = to_float(row.get("price"))
        if t is None or entry is None:
            continue
        papers.append({"time_jst": t, "entry": entry})
    return papers


def collect_ltp_window(rows, start_jst: datetime, end_jst: datetime):
    ltps = []
    for row in rows:
        t = parse_time_jst(row.get("time", ""))
        if t is None:
            continue
        if t < start_jst or t > end_jst:
            continue
        ltp = to_float(row.get("ltp"))
        if ltp is not None:
            ltps.append(ltp)
    return ltps


def calc_mae_mfe(entry: float, ltps: list):
    if not ltps:
        return None, None
    low = min(ltps)
    high = max(ltps)
    mae = (low - entry) / entry * 100.0
    mfe = (high - entry) / entry * 100.0
    return mae, mfe


def write_summary(logs_dir: Path, day_str: str, results: list):
    maes = [r["mae_pct"] for r in results if r.get("mae_pct") is not None]
    mfes = [r["mfe_pct"] for r in results if r.get("mfe_pct") is not None]
    avg_mae = (sum(maes) / len(maes)) if maes else None
    avg_mfe = (sum(mfes) / len(mfes)) if mfes else None

    out = logs_dir / f"mae_mfe_summary_{day_str}.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["day", "paper_cnt", "avg_mae_pct", "avg_mfe_pct"])
        w.writerow([
            day_str,
            len(results),
            f"{avg_mae:.3f}" if avg_mae is not None else "",
            f"{avg_mfe:.3f}" if avg_mfe is not None else ""
        ])
    print(f"[INFO] saved summary: {out}")


def main():
    csv_path = pick_today_file()
    day_str = csv_path.stem.replace("trade_log_", "")

    logs_dir = Path(__file__).resolve().parent.parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    rows = read_rows(csv_path)
    papers = read_papers(rows)

    print(f"PAPER件数: {len(papers)}")

    # 個別CSVの保存先
    detail_path = logs_dir / f"mae_mfe_detail_{day_str}.csv"
    detail_rows = []

    for i, p in enumerate(papers, 1):
        start = p["time_jst"]
        end = start + timedelta(minutes=WINDOW_MIN)

        ltps = collect_ltp_window(rows, start, end)
        mae, mfe = calc_mae_mfe(p["entry"], ltps)

        print("------------------------------")
        print(f"PAPER #{i}")
        print(f" time(JST): {start}")
        print(f" entry   : {p['entry']}")
        print(f" window  : {WINDOW_MIN} min / samples(log_ltp): {len(ltps)}")
        if mae is None or mfe is None:
            print(" MAE/MFE : 計算不可（窓内データ不足）")
        else:
            print(f" MAE : {mae:.3f}%")
            print(f" MFE : {mfe:.3f}%")

        # 個別CSV用に保存（ここがB）
        detail_rows.append({
            "day": day_str,
            "idx": i,
            "entry_time_jst": start.strftime("%Y-%m-%d %H:%M:%S"),
            "entry_price": p["entry"],
            "mae_pct": round(mae, 3) if mae is not None else "",
            "mfe_pct": round(mfe, 3) if mfe is not None else "",
            "window_min": WINDOW_MIN,
            "samples": len(ltps),
        })

    # ===== 個別CSVを書き出し（ここがC）=====
    if detail_rows:
        with open(detail_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(detail_rows[0].keys()))
            w.writeheader()
            w.writerows(detail_rows)
        print(f"[INFO] saved detail: {detail_path}")
    else:
        print("[INFO] detail rows: 0 (no PAPER)")

    print("------------------------------")
    write_summary(logs_dir, day_str, detail_rows)


if __name__ == "__main__":
    main()
