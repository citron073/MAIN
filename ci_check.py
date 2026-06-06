#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


MAIN_DIR = Path(__file__).resolve().parent
LOG_DIR = MAIN_DIR.parent / "logs"
DAILY_OUT_DIR = MAIN_DIR / "daily_report_out"
AUDIT_OUT_DIR = MAIN_DIR / "audit_out"


def _run(cmd: List[str], cwd: Path) -> Tuple[int, str]:
    p = subprocess.run(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return p.returncode, p.stdout


def _load_json(p: Path) -> Dict[str, Any]:
    txt = p.read_text(encoding="utf-8")
    return json.loads(txt)


def _err(msg: str) -> None:
    print(f"[ERROR] {msg}")
    sys.exit(1)


def _warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def _ok(msg: str) -> None:
    print(f"[OK] {msg}")


def streamlit_compat_checks(main_dir: Path) -> None:
    targets = [
        main_dir / "dashboard.py",
        main_dir / "keiba_dashboard.py",
    ]
    hits: List[str] = []
    for p in targets:
        if not p.exists():
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        for ln, line in enumerate(lines, start=1):
            # use_container_width is valid in Streamlit 1.x — skip
            # Check for genuinely removed APIs instead
            for deprecated in ("st.beta_", "st.experimental_rerun()",):
                if deprecated in line:
                    hits.append(f"{p.name}:{ln}: {line.strip()}")

    if hits:
        print("[ERROR] streamlit compatibility check failed: removed API found.")
        for h in hits[:30]:
            print(f"  - {h}")
        if len(hits) > 30:
            print(f"  ... and {len(hits) - 30} more")
        sys.exit(1)

    _ok("streamlit_compat: PASS")


def pick_latest_day8() -> Optional[str]:
    if not LOG_DIR.exists():
        return None
    cands = sorted(LOG_DIR.glob("trade_log_*.csv"), reverse=True)
    for p in cands:
        name = p.name
        # trade_log_YYYYMMDD.csv
        if len(name) == len("trade_log_YYYYMMDD.csv") and name.startswith("trade_log_") and name.endswith(".csv"):
            day8 = name[len("trade_log_"):-len(".csv")]
            if day8.isdigit() and len(day8) == 8:
                return day8
    return None


def _sum_int(d: Dict[str, Any], key: str) -> int:
    v = d.get(key)
    try:
        return int(v)
    except Exception:
        return 0


def semantic_checks(day8: str, daily_path: Path, audit_path: Path) -> None:
    d = _load_json(daily_path)
    a = _load_json(audit_path)

    # ---------- daily_report semantic ----------
    daily = d.get("daily", {})
    by_side = d.get("by_side", {})
    by_hour = d.get("by_hour", {})

    # 1) by_hour keys 0-23
    missing_hours = [str(h) for h in range(24) if str(h) not in by_hour]
    if missing_hours:
        _err(f"daily_report by_hour missing hours: {missing_hours}")

    # 2) by_side keys BUY/SELL/UNKNOWN
    for s in ("BUY", "SELL", "UNKNOWN"):
        if s not in by_side:
            _err(f"daily_report by_side missing side: {s}")

    # 3) daily totals vs by_side sums
    paper_daily = _sum_int(daily, "paper_n")
    exit_daily = _sum_int(daily, "exit_n")
    observe_daily = _sum_int(daily, "observe_n")

    paper_by_side = sum(_sum_int(by_side.get(s, {}), "paper_n") for s in ("BUY", "SELL", "UNKNOWN"))
    exit_by_side = sum(_sum_int(by_side.get(s, {}), "exit_n") for s in ("BUY", "SELL", "UNKNOWN"))
    # observe は by_side に無い設計もあるので、あればチェック（無ければスキップ）
    if all(isinstance(by_side.get(s, {}).get("observe_n", None), (int, str)) for s in ("BUY", "SELL", "UNKNOWN")):
        observe_by_side = sum(_sum_int(by_side.get(s, {}), "observe_n") for s in ("BUY", "SELL", "UNKNOWN"))
        if observe_by_side != observe_daily:
            _err(f"observe_n mismatch: daily={observe_daily} vs by_side_sum={observe_by_side}")
    else:
        _warn("by_side.observe_n not present (skip observe_n side-sum check)")

    if paper_by_side != paper_daily:
        _err(f"paper_n mismatch: daily={paper_daily} vs by_side_sum={paper_by_side}")
    if exit_by_side != exit_daily:
        _err(f"exit_n mismatch: daily={exit_daily} vs by_side_sum={exit_by_side}")

    # 4) daily totals vs by_hour sums
    paper_by_hour = sum(_sum_int(by_hour.get(str(h), {}), "paper_n") for h in range(24))
    exit_by_hour = sum(_sum_int(by_hour.get(str(h), {}), "exit_n") for h in range(24))
    observe_by_hour = sum(_sum_int(by_hour.get(str(h), {}), "observe_n") for h in range(24))

    if paper_by_hour != paper_daily:
        _err(f"paper_n mismatch: daily={paper_daily} vs by_hour_sum={paper_by_hour}")
    if exit_by_hour != exit_daily:
        _err(f"exit_n mismatch: daily={exit_daily} vs by_hour_sum={exit_by_hour}")
    if observe_by_hour != observe_daily:
        _err(f"observe_n mismatch: daily={observe_daily} vs by_hour_sum={observe_by_hour}")

    # ---------- audit semantic ----------
    summary = a.get("summary", {})
    # 5) rows: audit.summary.rows == daily.meta.rows_total (single-day)
    meta = d.get("meta", {})
    rows_total = int(meta.get("rows_total", 0) or 0)
    rows_used = int(meta.get("rows_used", 0) or 0)
    audit_rows = int(summary.get("rows", 0) or 0)

    if rows_total and audit_rows and rows_total != audit_rows:
        _err(f"rows_total mismatch: daily.meta.rows_total={rows_total} vs audit.summary.rows={audit_rows}")

    # rows_used はドロップが無い日なら rows_total と一致するはず（ズレてもWARN止まり）
    rows_dropped = int(meta.get("rows_dropped", 0) or 0)
    if rows_total and rows_used and rows_total != rows_used and rows_dropped == 0:
        _warn(f"daily.meta.rows_used({rows_used}) != rows_total({rows_total}) but rows_dropped=0 (check)")

    # 6) audit has zero issues expectation here is not hard-coded.
    #    spec_check already verifies schema. Here we only check consistency when issues exist.
    issues = a.get("issues", [])
    if isinstance(issues, list):
        for it in issues:
            if isinstance(it, dict):
                sev = (it.get("severity") or "").strip().upper()
                if sev in ("FATAL", "ERROR"):
                    _err(f"audit contains {sev} issue: {it.get('code')} {it.get('message')}")
    else:
        _err("audit.issues must be a list")

    _ok("semantic_checks: PASS")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("day8", nargs="?", default=None, help="YYYYMMDD (default: latest log day)")
    args = ap.parse_args()

    day8 = (args.day8 or "").strip() if args.day8 else ""
    if not day8:
        day8 = pick_latest_day8() or ""
    if not (day8.isdigit() and len(day8) == 8):
        _err("day8 is required (YYYYMMDD) and must exist in ../logs as trade_log_YYYYMMDD.csv")

    # 0) compile gate
    rc, out = _run(
        [
            sys.executable,
            "-m",
            "py_compile",
            "bot.py",
            "daily_report.py",
            "audit.py",
            "dashboard.py",
            "spec_check.py",
            "exchange/bitflyer_private.py",
            "tools/keychain_secret.py",
            "tools/live_preflight.py",
        ],
        cwd=MAIN_DIR,
    )
    if rc != 0:
        print(out)
        _err("py_compile failed")

    # 0.5) streamlit compatibility gate (future-proof deprecations)
    streamlit_compat_checks(MAIN_DIR)

    # 1) daily_report generate
    DAILY_OUT_DIR.mkdir(parents=True, exist_ok=True)
    rc, out = _run([sys.executable, "daily_report.py", day8], cwd=MAIN_DIR)
    print(out.strip())
    if rc != 0:
        _err("daily_report.py failed")

    # 2) audit generate (MAIN/audit_out)
    AUDIT_OUT_DIR.mkdir(parents=True, exist_ok=True)
    rc, out = _run([sys.executable, "audit.py", "--day", day8, "--out-dir", "audit_out"], cwd=MAIN_DIR)
    print(out.strip())
    if rc != 0:
        _err("audit.py failed")

    # 3) spec_check strict
    rc, out = _run([sys.executable, "spec_check.py", day8, "--strict"], cwd=MAIN_DIR)
    print(out.strip())
    if rc != 0:
        _err("spec_check.py failed (strict)")

    # 4) semantic checks
    daily_path = DAILY_OUT_DIR / f"daily_report_{day8}.json"
    audit_path = AUDIT_OUT_DIR / f"audit_{day8}.json"
    if not daily_path.exists():
        _err(f"missing daily_report json: {daily_path}")
    if not audit_path.exists():
        _err(f"missing audit json: {audit_path}")

    semantic_checks(day8, daily_path, audit_path)
    _ok(f"ci_check.py done (DAY8={day8})")


if __name__ == "__main__":
    main()
