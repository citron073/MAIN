import csv
from pathlib import Path
from collections import Counter

FILTER_START_HOUR = 10
FILTER_END_HOUR = 16   # ← 10〜15台まで含めたいなら16推奨（15:xxを含む）

def parse_hour(timestr: str):
    try:
        return int(timestr[11:13])
    except:
        return None

def in_filter(hour: int) -> bool:
    return FILTER_START_HOUR <= hour < FILTER_END_HOUR

def read_rows(path: Path):
    rows = []
    with open(path, newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(row)
    return rows

def count_paper_observe(rows):
    c = Counter((r.get("result") or "") for r in rows)
    paper = c.get("PAPER", 0)
    observe = sum(v for k, v in c.items() if k.startswith("OBSERVE"))
    denom = paper + observe
    rate = (paper / denom * 100.0) if denom > 0 else None
    return paper, observe, rate

def main():
    files = sorted(Path(".").glob("trade_log_*.csv"))
    if not files:
        print("[ERROR] trade_log_*.csv が見つかりません")
        return

    print("date | PAPER_rate_all(%) | PAPER_rate_10-15(%)")
    print("------------------------------------------------")

    for p in files:
        day = p.stem.replace("trade_log_", "")
        rows = read_rows(p)

        # 全時間
        paper_all, obs_all, rate_all = count_paper_observe(rows)

        # フィルタ
        frows = []
        for r in rows:
            h = parse_hour(r.get("time", ""))
            if h is None:
                continue
            if in_filter(h):
                frows.append(r)

        paper_f, obs_f, rate_f = count_paper_observe(frows)

        def fmt(x):
            return "N/A" if x is None else f"{x:5.1f}%"

        print(f"{day} | {fmt(rate_all):>14} | {fmt(rate_f):>16}")

if __name__ == "__main__":
    main()
