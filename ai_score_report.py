# MAIN/ai_score_report.py
# ============================================================
# AIスコア分布レポート（pos_id突合 / バケット集計 / CSV出力）
# - trade_log_*.csv を読む
# - pos_id単位で PAPER と PAPER_EXIT_* を突合
# - note 内 "AI score=0.xxx" を抽出（entry優先）
# - バケット集計をCSV出力
# ============================================================

import argparse
import csv
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict, Counter
from typing import Dict, Any, List, Optional


def eprint(*a):
    print(*a, file=sys.stderr)


def safe_float(x) -> Optional[float]:
    try:
        return float(str(x).strip())
    except Exception:
        return None


def parse_time(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def get_logs_dir() -> Path:
    here = Path(__file__).resolve().parent
    for p in [
        here.parent / "logs",
        here / "logs",
        Path("../logs").resolve(),
        Path("./logs").resolve(),
    ]:
        if p.exists() and any(p.glob("trade_log_*.csv")):
            return p
    return here.parent / "logs"


def read_rows(p: Path) -> List[Dict[str, str]]:
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_rows(p: Path, fieldnames: List[str], rows: List[Dict[str, Any]]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


STRICT_PID_RE = re.compile(r"\bpos_id=([0-9]{8}-[0-9]{6}-[A-Z]+-\d{3})\b")
AI_SCORE_RE = re.compile(r"\bAI\s+score=([0-9]*\.[0-9]+|[0-9]+)\b")

RESULT_PAPER = "PAPER"
RESULT_EXIT_PREFIX = "PAPER_EXIT_"

OUTCOME_ORDER = ["TP", "SL", "TIMEOUT", "PARTIAL_TP", "EOD", "UNKNOWN", "NO_EXIT"]


def extract_pos_id(row: Dict[str, str]) -> str:
    pid = (row.get("pos_id") or "").strip()
    if pid:
        return pid
    note = (row.get("note") or "").strip()
    m = STRICT_PID_RE.search(note)
    return m.group(1) if m else ""


def extract_ai_score(row: Dict[str, str]) -> Optional[float]:
    note = (row.get("note") or "").strip()
    if not note:
        return None
    m = AI_SCORE_RE.search(note)
    if not m:
        return None
    v = safe_float(m.group(1))
    if v is None:
        return None
    if v < 0:
        v = 0.0
    if v > 1:
        v = 1.0
    return v


def outcome_from_result(result: str) -> str:
    r = (result or "").strip()
    if r == "PAPER_EXIT_TP":
        return "TP"
    if r == "PAPER_EXIT_SL":
        return "SL"
    if r == "PAPER_EXIT_TIMEOUT":
        return "TIMEOUT"
    if r == "PAPER_EXIT_PARTIAL_TP":
        return "PARTIAL_TP"
    if r == "PAPER_EXIT_EOD":
        return "EOD"
    if r.startswith(RESULT_EXIT_PREFIX):
        return "UNKNOWN"
    return "UNKNOWN"


def bucketize(score: float, step: float) -> str:
    if score >= 1.0:
        lo = 1.0 - step
        hi = 1.0
    else:
        k = int(score / step)
        lo = k * step
        hi = (k + 1) * step
    return f"{lo:.2f}-{hi:.2f}"


def find_files(logs_dir: Path, days: int) -> List[Path]:
    files = sorted(logs_dir.glob("trade_log_*.csv"))
    if not files:
        return []
    if days <= 0:
        return files

    cutoff = datetime.now().date() - timedelta(days=days - 1)
    out = []
    for p in files:
        m = re.search(r"trade_log_(\d{8})\.csv", p.name)
        if not m:
            continue
        try:
            d = datetime.strptime(m.group(1), "%Y%m%d").date()
        except Exception:
            continue
        if d >= cutoff:
            out.append(p)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="直近N日（0以下で全期間）")
    ap.add_argument("--bucket_step", type=float, default=0.10, help="AIスコア刻み（例: 0.10）")
    ap.add_argument("--min_per_bucket", type=int, default=5, help="バケット最小件数の注意しきい")
    ap.add_argument("--out", type=str, default=None, help="出力CSVパス（省略時は logs/reports/ に自動）")
    args = ap.parse_args()

    logs_dir = get_logs_dir()
    files = find_files(logs_dir, args.days)
    if not files:
        print("trade_log_*.csv not found")
        return

    all_rows: List[Dict[str, str]] = []
    for p in files:
        try:
            all_rows.extend(read_rows(p))
        except Exception as e:
            eprint(f"[WARN] read failed: {p} err={e}")

    def sort_key(r: Dict[str, str]):
        t = parse_time(r.get("time", ""))
        return t or datetime.min

    all_rows.sort(key=sort_key)

    by_pid: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    pid_missing_rows = 0

    for r in all_rows:
        pid = extract_pos_id(r)
        if not pid:
            pid_missing_rows += 1
            continue
        by_pid[pid].append(r)

    pid_records = []
    no_paper = 0
    no_exit = 0
    ai_missing = 0

    for pid, rs in by_pid.items():
        rs_sorted = sorted(rs, key=sort_key)
        entry = next((x for x in rs_sorted if (x.get("result") or "") == RESULT_PAPER), None)
        exit_ = next((x for x in rs_sorted if (x.get("result") or "").startswith(RESULT_EXIT_PREFIX)), None)

        if entry is None:
            no_paper += 1
            continue

        outc = "NO_EXIT"
        exit_time = ""
        if exit_ is not None:
            outc = outcome_from_result(exit_.get("result", ""))
            exit_time = (exit_.get("time") or "").strip()
        else:
            no_exit += 1

        score = extract_ai_score(entry)
        if score is None:
            for x in rs_sorted:
                score = extract_ai_score(x)
                if score is not None:
                    break

        if score is None:
            ai_missing += 1

        pid_records.append({
            "pid": pid,
            "entry_time": (entry.get("time") or "").strip(),
            "exit_time": exit_time,
            "outcome": outc,
            "ai_score": "" if score is None else f"{score:.6f}",
        })

    bucket_step = float(args.bucket_step)
    if bucket_step <= 0 or bucket_step > 0.5:
        bucket_step = 0.10

    bucket_cnt = Counter()
    bucket_outcome_cnt: Dict[str, Counter] = defaultdict(Counter)

    total_with_score = 0
    for rec in pid_records:
        s = safe_float(rec.get("ai_score", ""))
        if s is None:
            continue
        total_with_score += 1
        b = bucketize(s, bucket_step)
        bucket_cnt[b] += 1
        bucket_outcome_cnt[b][rec["outcome"]] += 1

    print("\n=== AI SCORE BUCKET REPORT ===")
    print(f"logs_dir: {logs_dir}")
    print(f"files: {len(files)} (days={args.days})")
    print(f"rows_total: {len(all_rows)}  pid_groups: {len(by_pid)}  pid_missing_rows: {pid_missing_rows}")
    print(f"pid_records(PAPER only): {len(pid_records)}  no_exit: {no_exit}  ai_missing: {ai_missing}")
    print(f"bucket_step: {bucket_step:.2f}  with_ai_score: {total_with_score}")

    if total_with_score == 0:
        print("\n[INFO] AIスコアが見つかりませんでした（noteに 'AI score=...' が必要）")
        return

    def bucket_key(b: str) -> float:
        try:
            return float(b.split("-")[0])
        except Exception:
            return 0.0

    buckets_sorted = sorted(bucket_cnt.keys(), key=bucket_key)

    print("\nbucket | n | TP% | SL% | TIMEOUT% | PARTIAL% | EOD% | NO_EXIT% | note")
    print("-" * 78)

    rows_out = []
    for b in buckets_sorted:
        n = bucket_cnt[b]
        oc = bucket_outcome_cnt[b]
        denom = max(1, n)

        tp = oc.get("TP", 0)
        sl = oc.get("SL", 0)
        to = oc.get("TIMEOUT", 0)
        pt = oc.get("PARTIAL_TP", 0)
        eod = oc.get("EOD", 0)
        nx = oc.get("NO_EXIT", 0)
        unk = oc.get("UNKNOWN", 0)

        tp_pct = tp / denom * 100.0
        sl_pct = sl / denom * 100.0
        to_pct = to / denom * 100.0
        pt_pct = pt / denom * 100.0
        eod_pct = eod / denom * 100.0
        nx_pct = nx / denom * 100.0

        note = ""
        if n < args.min_per_bucket:
            note = f"LOW_N(<{args.min_per_bucket})"
        if unk > 0:
            note = (note + " " if note else "") + f"UNKNOWN={unk}"

        print(f"{b} | {n:4d} | {tp_pct:5.1f} | {sl_pct:5.1f} | {to_pct:8.1f} | {pt_pct:7.1f} | {eod_pct:5.1f} | {nx_pct:8.1f} | {note}")

        rows_out.append({
            "bucket": b,
            "n": n,
            "tp": tp,
            "sl": sl,
            "timeout": to,
            "partial_tp": pt,
            "eod": eod,
            "no_exit": nx,
            "unknown": unk,
            "tp_pct": f"{tp_pct:.2f}",
            "sl_pct": f"{sl_pct:.2f}",
            "timeout_pct": f"{to_pct:.2f}",
            "partial_tp_pct": f"{pt_pct:.2f}",
            "eod_pct": f"{eod_pct:.2f}",
            "no_exit_pct": f"{nx_pct:.2f}",
        })

    tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.out:
        out_path = Path(args.out)
    else:
        out_path = logs_dir / "reports" / f"ai_score_buckets_{tag}.csv"

    write_rows(
        out_path,
        fieldnames=[
            "bucket", "n",
            "tp", "sl", "timeout", "partial_tp", "eod", "no_exit", "unknown",
            "tp_pct", "sl_pct", "timeout_pct", "partial_tp_pct", "eod_pct", "no_exit_pct",
        ],
        rows=rows_out
    )

    detail_path = out_path.with_name(out_path.stem.replace("ai_score_buckets_", "ai_score_detail_") + ".csv")
    write_rows(
        detail_path,
        fieldnames=["pid", "entry_time", "exit_time", "outcome", "ai_score"],
        rows=pid_records
    )

    print(f"\n[WRITE] {out_path}")
    print(f"[WRITE] {detail_path}")
    print("\n[OK] ai_score_report done")


if __name__ == "__main__":
    main()
