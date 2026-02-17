#!/usr/bin/env python3
import csv
import re
import json
import glob
from pathlib import Path
from collections import defaultdict

LOG_DIR = Path("../logs").resolve()
STATE_FILE = Path("state.json")

re_tm = re.compile(r"timeout_mode=([A-Z_]+)")

# current open_pos
cur = None
if STATE_FILE.exists():
    d = json.load(open(STATE_FILE))
    cur = (d.get("_open_pos") or {}).get("pos_id")

info = defaultdict(lambda: {
    "tm": None,
    "extended": False,
    "exit": None,
    "last_res": None,
})

for fp in glob.glob(str(LOG_DIR / "trade_log_*.csv")):
    with open(fp, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            pid = (row.get("pos_id") or "").strip()
            if not pid:
                continue

            res  = (row.get("result") or "").strip()
            note = (row.get("note") or "")

            info[pid]["last_res"] = res

            if res == "PAPER":
                m = re_tm.search(note)
                if m:
                    info[pid]["tm"] = m.group(1)

            if res == "HOLD_OPEN_POS" and "EXTENDED exp=" in note:
                info[pid]["extended"] = True

            if res.startswith("PAPER_EXIT_") or res in (
                "PAPER_EXIT_EOD",
                "MANUAL_CLEAR_OPEN_POS",
            ):
                info[pid]["exit"] = res

# 対象：timeout_mode=EXTEND で建てたpos
targets = {pid:v for pid,v in info.items() if v["tm"] == "EXTEND"}

# orphan判定：exit無し & 現在openでない & 状態が途中
orphan = set(
    pid for pid,v in targets.items()
    if (v["exit"] is None)
    and (pid != cur)
    and (v.get("last_res") in ("PAPER","HOLD_OPEN_POS"))
)

extended = sum(
    1 for pid,v in targets.items()
    if v["extended"] and pid not in orphan
)
timeout = sum(
    1 for pid,v in targets.items()
    if v["exit"] == "PAPER_EXIT_TIMEOUT" and pid not in orphan
)

den = extended + timeout
rate = (extended / den * 100.0) if den else 0.0

print("current_open_pos =", cur)
print("TARGET_EXTEND_POS =", len(targets))
print("ORPHAN_EXCLUDED   =", len(orphan))
print("EXTENDED(valid)   =", extended)
print("TIMEOUT(valid)    =", timeout)
print(f"EXTEND_SUCCESS(valid only) = {rate:.1f}% (den={den})")

if orphan:
    print("\n[ORPHAN LIST]")
    for pid in sorted(orphan):
        print("-", pid, "last_res=", targets[pid]["last_res"])
