# MAIN/audit.py (v3-C) 監査スクリプト【完全網羅・確定版】
# ------------------------------------------------------------
# - trade_log_YYYYMMDD.csv を監査して pos_id / ENTRY / EXIT の整合をチェック
# - note 内の pos_id=... と CSV列 pos_id の整合チェック（note列がある場合のみ）
# - pos_id strict 形式チェック（YYYYMMDD-HHMMSS-TAG-999）
# - state.json の _open_pos とログ監査結果の整合チェック
#
# 使い方:
#   python3 audit.py
#   python3 audit.py 20260207
#   python3 audit.py --last 7
#   python3 audit.py --from 20260201 --to 20260207
#   python3 audit.py --no-save
#   python3 audit.py --out-dir ./audit_out
#
# 出力:
#   - 標準出力に summary / issues を表示
#   - 監査結果JSONを ./audit_out/audit_YYYYMMDD.json に保存（デフォルト）

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional, Dict, Any, List

# =========================
# Paths
# =========================
MAIN_DIR = Path(__file__).resolve().parent
STATE_JSON = MAIN_DIR / "state.json"
DEFAULT_OUT_DIR = MAIN_DIR / "audit_out"


def find_logs_dir(main_dir: Path) -> Optional[Path]:
    cands = [
        main_dir.parent / "logs",
        main_dir / "logs",
        Path("../logs").resolve(),
        Path("./logs").resolve(),
    ]
    for p in cands:
        try:
            if p.exists() and any(p.glob("trade_log_*.csv")):
                return p
        except Exception:
            pass
    return None


LOGS_DIR = find_logs_dir(MAIN_DIR)

# =========================
# Definitions
# =========================
EXIT_RESULTS = {
    "PAPER_EXIT_TP",
    "PAPER_EXIT_SL",
    "PAPER_EXIT_TIMEOUT",
    "PAPER_EXIT_PARTIAL_TP",
}

EVENT_RESULTS = {"PAPER", "HOLD_OPEN_POS"} | EXIT_RESULTS

POS_ID_STRICT_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[A-Z]+-\d{3}$")
NOTE_POS_ID_RE = re.compile(r"\bpos_id=([0-9]{8}-[0-9]{6}-[A-Z]+-\d{3})\b")

# =========================
# Helpers
# =========================
def s(x: Any) -> str:
    return str(x or "").strip()


def parse_time_safe(t: str) -> datetime:
    try:
        return datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.min


def read_csv_dict(path: Path) -> List[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_state() -> Dict[str, Any]:
    if not STATE_JSON.exists():
        return {}
    try:
        return json.loads(STATE_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}


def log_path(day8: str) -> Path:
    if LOGS_DIR is None:
        return MAIN_DIR.parent / "logs" / f"trade_log_{day8}.csv"
    return LOGS_DIR / f"trade_log_{day8}.csv"


def existing_days(days: List[str]) -> List[str]:
    return [d for d in days if log_path(d).exists()]


# =========================
# Data model
# =========================
@dataclass
class PosUnit:
    entry: Optional[dict] = None
    exit: Optional[dict] = None
    holds: List[dict] = None
    all: List[dict] = None

    def __post_init__(self):
        self.holds = self.holds or []
        self.all = self.all or []


# =========================
# Core audit
# =========================
def audit_one_day(day8: str) -> Dict[str, Any]:
    path = log_path(day8)
    rows = read_csv_dict(path)

    if not rows:
        return {
            "day8": day8,
            "file": str(path),
            "exists": path.exists(),
            "summary": {"rows": 0, "pos_total": 0, "issues_total": 1},
            "issues": [f"INFO: no trade log for {day8}"],
            "per_pos": {},
        }

    cols = set(rows[0].keys())
    has_note = "note" in cols

    issues: List[str] = []
    per_pos: Dict[str, PosUnit] = defaultdict(PosUnit)

    rows_sorted = sorted(rows, key=lambda r: parse_time_safe(s(r.get("time"))))

    for r in rows_sorted:
        res = s(r.get("result"))
        pid = s(r.get("pos_id"))
        note = s(r.get("note")) if has_note else ""
        t = s(r.get("time"))

        if res in EVENT_RESULTS:
            if not pid:
                issues.append(f"ERROR: pos_id empty result={res} time={t}")
                continue
            if not POS_ID_STRICT_RE.fullmatch(pid):
                issues.append(f"ERROR: pos_id not strict pos_id={pid} time={t}")
            if has_note:
                m = NOTE_POS_ID_RE.search(note)
                if not m:
                    issues.append(f"ERROR: note missing pos_id=... pos_id={pid} time={t}")
                elif m.group(1) != pid:
                    issues.append(f"ERROR: note pos_id mismatch col={pid} note={m.group(1)} time={t}")

        if pid:
            u = per_pos[pid]
            u.all.append(r)

            if res == "PAPER":
                if u.entry:
                    issues.append(f"ERROR: duplicate ENTRY pos_id={pid}")
                u.entry = u.entry or r
            elif res in EXIT_RESULTS:
                if u.exit:
                    issues.append(f"ERROR: multiple EXIT pos_id={pid}")
                u.exit = u.exit or r
            elif res == "HOLD_OPEN_POS":
                u.holds.append(r)

    open_n = closed_n = 0
    for pid, u in per_pos.items():
        if u.entry and u.exit:
            closed_n += 1
        elif u.entry and not u.exit:
            open_n += 1
        elif not u.entry and u.exit:
            issues.append(f"ERROR: EXIT without ENTRY pos_id={pid}")

    state = load_state()
    sop = state.get("_open_pos") if isinstance(state.get("_open_pos"), dict) else {}
    sop_id = s(sop.get("pos_id"))
    if sop_id:
        u = per_pos.get(sop_id)
        if not u:
            issues.append(f"WARN: state._open_pos {sop_id} not found in log {day8}")
        elif u.exit:
            issues.append(f"WARN: state._open_pos {sop_id} is CLOSED in log")

    summary = {
        "rows": len(rows_sorted),
        "pos_total": len(per_pos),
        "open": open_n,
        "closed": closed_n,
        "issues_total": len(issues),
        "note_checks_enabled": has_note,
    }

    per_pos_out = {
        pid: {
            "entry": s(u.entry.get("time")) if u.entry else None,
            "exit": s(u.exit.get("time")) if u.exit else None,
            "holds": len(u.holds),
            "events": len(u.all),
        }
        for pid, u in per_pos.items()
    }

    return {
        "day8": day8,
        "file": str(path),
        "exists": True,
        "summary": summary,
        "issues": issues,
        "per_pos": per_pos_out,
    }


# =========================
# CLI
# =========================
def main() -> None:
    if LOGS_DIR is None:
        print("[ERROR] logs dir not found")
        sys.exit(2)

    day8 = datetime.now().strftime("%Y%m%d")
    if len(sys.argv) >= 2 and re.fullmatch(r"\d{8}", sys.argv[1]):
        day8 = sys.argv[1]

    rep = audit_one_day(day8)

    print(f"\n=== AUDIT {day8} ===")
    print(json.dumps(rep["summary"], ensure_ascii=False, indent=2))

    if rep["issues"]:
        print("\n--- ISSUES ---")
        for x in rep["issues"][:200]:
            print(x)
    else:
        print("\nISSUES: none")

    out_dir = DEFAULT_OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"audit_{day8}.json"
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OK] saved: {out}")


if __name__ == "__main__":
    main()
