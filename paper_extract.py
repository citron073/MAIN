import csv
from pathlib import Path

LOG_FILE = Path("trade_log_20260122.csv")

def main():
    if not LOG_FILE.exists():
        print("[ERROR] log file not found")
        return

    papers = []

    with open(LOG_FILE, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("result") == "PAPER":
                papers.append(row)

    print(f"PAPER件数: {len(papers)}\n")

    for i, p in enumerate(papers, 1):
        print(f"PAPER #{i}")
        print(f" time : {p['time']}")
        print(f" side : {p['side']}")
        print(f" price: {p['price']}")
        print(f" trend: {p.get('trend')}")
        print(f" signal: {p.get('signal')}")
        print("-" * 30)

if __name__ == "__main__":
    main()
