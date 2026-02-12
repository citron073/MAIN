import csv
from datetime import datetime
from collections import defaultdict

LOG_FILE = "trade_log.csv"

def to_float(x, default=None):
    try:
        if x is None or x == "":
            return default
        return float(x)
    except ValueError:
        return default

def analyze_by_hour():
    by_hour = defaultdict(lambda: {
        "total": 0,
        "paper": 0,
        "skip_spread": 0,
        "spreads": []
    })

    with open(LOG_FILE, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            time_str = row.get("time", "")
            if not time_str:
                continue

            dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            hour = dt.hour

            by_hour[hour]["total"] += 1

            if row.get("result") == "PAPER":
                by_hour[hour]["paper"] += 1
            if row.get("result") == "SKIP_SPREAD":
                by_hour[hour]["skip_spread"] += 1

            sp = to_float(row.get("spread_pct"))
            if sp is not None:
                by_hour[hour]["spreads"].append(sp)

    return by_hour

def print_report(by_hour):
    print("\n時間帯分析（hour別）")
    print("hour | total | PAPER | PAPER率 | SKIP_SPREAD | avg_spread(%)")
    print("-" * 72)

    for hour in sorted(by_hour.keys()):
        d = by_hour[hour]
        spreads = d["spreads"]
        avg = sum(spreads) / len(spreads) if spreads else None
        avg_txt = f"{avg:.4f}" if avg is not None else "—"

        paper_rate = (d["paper"] / d["total"]) if d["total"] > 0 else 0
        paper_rate_txt = f"{paper_rate*100:.1f}%"

        print(
            f"{hour:>4} | "
            f"{d['total']:>5} | "
            f"{d['paper']:>5} | "
            f"{paper_rate_txt:>7} | "
            f"{d['skip_spread']:>11} | "
            f"{avg_txt:>13}"
        )
    # 稼働候補（平均spreadが閾値未満のhour）
    candidates = []
    for hour in sorted(by_hour.keys()):
        d = by_hour[hour]
        spreads = d["spreads"]
        if not spreads:
            continue
        avg = sum(spreads) / len(spreads)
        if avg < 0.05:  # 0.05%
            candidates.append(hour)

    print("\n稼働候補（平均spread < 0.05%）:", candidates if candidates else "該当なし（データ不足 or 閾値未満なし）")

def main():
    by_hour = analyze_by_hour()
    if not by_hour:
        print("ログがありません。")
        return
    print_report(by_hour)

if __name__ == "__main__":
    main()
