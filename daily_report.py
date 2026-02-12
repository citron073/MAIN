#!/usr/bin/env python3
# ============================================================
# daily_report.py (Wrapper v2: ai_training_log optional)
#
# Default:
#   python3 daily_report.py
#     -> runs legacy daily_report_legacy.py (compat)
#
# AI one-button:
#   python3 daily_report.py --ai run --days 90 --min_trades 80
#
# Notes:
#   - If ai_training_log.csv is missing, this wrapper will build
#     training rows from ../logs/trade_log_YYYYMMDD.csv (pos_id + AI score).
# ============================================================

from __future__ import annotations
import argparse
import csv
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
import runpy

MAIN = Path(__file__).resolve().parent
LEGACY = MAIN / "daily_report_legacy.py"
AI_MODEL = MAIN / "ai_model.json"

LOGS_DIR = MAIN.parent / "logs"

AI_SCORE_RE = re.compile(r"\bAI(?:_EXT)?\s*score=([0-9]*\.[0-9]+)\b", re.I)

def _now():
    return datetime.now()

def _load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default

def _save_json(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def _parse_float(x):
    try:
        if x is None: return None
        s = str(x).strip()
        if s == "": return None
        return float(s)
    except Exception:
        return None

def _parse_time(s: str):
    try:
        return datetime.strptime(str(s).strip(), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None

def _outcome_bucket(outcome: str) -> str:
    o = (outcome or "").strip().upper()
    if o == "TP" or o.endswith("_TP"): return "WIN"
    if o == "SL" or o.endswith("_SL"): return "LOSS"
    if o == "TIMEOUT" or o.endswith("_TIMEOUT"): return "NEUTRAL"
    if "PARTIAL" in o: return "NEUTRAL"
    if "EOD" in o: return "NEUTRAL"
    return "UNKNOWN"

def _find_ai_training_log():
    # common candidates
    cands = [
        MAIN / "ai_training_log.csv",
        LOGS_DIR / "ai_training_log.csv",
    ]
    for p in cands:
        if p.exists():
            return p
    # any similarly named file
    if LOGS_DIR.exists():
        for p in sorted(LOGS_DIR.glob("ai_training_log*.csv")):
            if p.exists():
                return p
    if MAIN.exists():
        for p in sorted(MAIN.glob("ai_training_log*.csv")):
            if p.exists():
                return p
    return None

def _iter_csv_rows(path: Path):
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            yield row

def _extract_ai_score_from_note(note: str):
    if not note:
        return None
    m = AI_SCORE_RE.search(note)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None

def _collect_trade_logs(days: int):
    """Return list of trade_log paths within lookback window (by filename date)."""
    if not LOGS_DIR.exists():
        return []
    cutoff_day8 = (_now() - timedelta(days=int(days))).strftime("%Y%m%d")
    out = []
    for p in sorted(LOGS_DIR.glob("trade_log_*.csv")):
        m = re.search(r"trade_log_(\d{8})\.csv$", p.name)
        if not m:
            continue
        day8 = m.group(1)
        if day8 >= cutoff_day8:
            out.append(p)
    return out

def _build_training_rows_from_trade_logs(days: int):
    """
    Build rows:
      time, pos_id, side, entry_price, exit_price, ai_score, outcome
    from trade_log_YYYYMMDD.csv
    """
    paths = _collect_trade_logs(days)
    if not paths:
        return [], "[NG] no trade_log_*.csv found in ../logs"

    # pos_id -> info from PAPER row
    paper = {}
    exits = []

    for p in paths:
        for row in _iter_csv_rows(p):
            t = _parse_time(row.get("time",""))
            if not t:
                continue
            res = (row.get("result") or "").strip()
            pos_id = (row.get("pos_id") or "").strip()
            note = row.get("note") or ""
            side = (row.get("side") or "").strip().upper()

            if res == "PAPER":
                # need pos_id, ai_score in note (or empty)
                if not pos_id:
                    continue
                ai_score = _extract_ai_score_from_note(note)
                paper[pos_id] = {
                    "time": t,
                    "pos_id": pos_id,
                    "side": side,
                    "entry_price": _parse_float(row.get("price")),
                    "ai_score": ai_score,
                }

            elif res.startswith("PAPER_EXIT_") or res in ("PAPER_EXIT_PARTIAL_TP", "PAPER_EXIT_EOD", "PAPER_EXIT_UNKNOWN"):
                if not pos_id:
                    continue
                exits.append({
                    "time": t,
                    "pos_id": pos_id,
                    "outcome": res.replace("PAPER_EXIT_", ""),
                    "exit_price": _parse_float(row.get("ltp")),
                })

    # merge
    out = []
    missing_link = 0
    for ex in exits:
        pid = ex["pos_id"]
        base = paper.get(pid)
        if not base:
            missing_link += 1
            continue
        ai_score = base.get("ai_score")
        out.append({
            "time": ex["time"],
            "pos_id": pid,
            "side": base.get("side"),
            "entry_price": base.get("entry_price"),
            "exit_price": ex.get("exit_price"),
            "ai_score": ai_score,
            "outcome": ex.get("outcome"),
        })

    msg = f"[OK] built from trade_logs: paper_pos={len(paper)} exits={len(exits)} merged={len(out)} missing_link={missing_link}"
    return out, msg

def _load_current_threshold():
    cfg = _load_json(AI_MODEL, {})
    th = cfg.get("confidence_threshold", {})
    try:
        cur = float(th.get("entry", 0.65))
    except Exception:
        cur = 0.65
    return cur, cfg

def _evaluate_threshold(rows, th):
    picked = []
    for r in rows:
        s = r.get("ai_score")
        if s is None:
            continue
        if s >= th:
            picked.append(r)

    n = len(picked)
    if n == 0:
        return {"n": 0, "win": 0, "loss": 0, "neutral": 0, "metric": -999}

    win = sum(1 for r in picked if r["bucket"] == "WIN")
    loss = sum(1 for r in picked if r["bucket"] == "LOSS")
    neutral = sum(1 for r in picked if r["bucket"] == "NEUTRAL")

    metric = (win - 2.0*loss - 0.5*neutral) / max(1, n)
    return {"n": n, "win": win, "loss": loss, "neutral": neutral, "metric": metric}

def ai_train_eval_apply(days: int, min_trades: int, apply: bool, verbose: bool):
    # 1) prefer ai_training_log.csv
    p = _find_ai_training_log()
    rows = []
    src = ""

    cutoff = _now() - timedelta(days=int(days))

    if p:
        src = f"ai_training_log={p}"
        for row in _iter_csv_rows(p):
            t = _parse_time(row.get("time",""))
            if not t or t < cutoff:
                continue
            sc = _parse_float(row.get("ai_score"))
            out = row.get("outcome") or row.get("result") or ""
            b = _outcome_bucket(out)
            if b == "UNKNOWN":
                continue
            rows.append({"time": t, "ai_score": sc, "outcome": out, "bucket": b})
    else:
        built, msg = _build_training_rows_from_trade_logs(days)
        src = msg
        for r in built:
            t = r.get("time")
            if not t or t < cutoff:
                continue
            sc = r.get("ai_score")
            out = r.get("outcome","")
            b = _outcome_bucket(out)
            if b == "UNKNOWN":
                continue
            rows.append({"time": t, "ai_score": sc, "outcome": out, "bucket": b})

    scored = [r for r in rows if r["ai_score"] is not None]
    print(f"[INFO] {src}")
    print(f"[INFO] window=last {days} days -> rows={len(rows)} scored_rows={len(scored)}")

    need = max(20, int(min_trades))
    if len(scored) < need:
        print(f"[NG] not enough scored rows: {len(scored)} < min_required={need}")
        print("     -> You need AI score in PAPER note (e.g., 'AI score=0.712'), or provide ai_training_log.csv.")
        return 2

    cur_th, cfg = _load_current_threshold()
    grid = [round(x, 2) for x in [0.50,0.55,0.60,0.65,0.70,0.75,0.80,0.85]]

    base = _evaluate_threshold(scored, cur_th)
    best = {"th": cur_th, **base}

    if verbose:
        print(f"[BASE] th={cur_th:.2f} -> n={base['n']} win={base['win']} loss={base['loss']} neutral={base['neutral']} metric={base['metric']:.4f}")

    for th in grid:
        ev = _evaluate_threshold(scored, th)
        if ev["n"] < min_trades:
            continue
        if ev["metric"] > best["metric"]:
            best = {"th": th, **ev}
        if verbose:
            print(f"[GRID] th={th:.2f} -> n={ev['n']} win={ev['win']} loss={ev['loss']} neutral={ev['neutral']} metric={ev['metric']:.4f}")

    print("\n[RESULT]")
    print(f"  current_th={cur_th:.2f} metric={base['metric']:.4f} n={base['n']}")
    print(f"  best_th   ={best['th']:.2f} metric={best['metric']:.4f} n={best['n']} (min_trades={min_trades})")

    improve = best["metric"] - base["metric"]
    if best["th"] == cur_th or improve < 0.02:
        print(f"[INFO] no safe improvement to apply (improve={improve:.4f} < 0.02 or same threshold).")
        return 0

    if not apply:
        print("[INFO] dry-run (no apply). Use: --ai apply or --ai run")
        return 0

    if not isinstance(cfg, dict):
        cfg = {}
    if "confidence_threshold" not in cfg or not isinstance(cfg.get("confidence_threshold"), dict):
        cfg["confidence_threshold"] = {}
    cfg["confidence_threshold"]["entry"] = float(best["th"])

    meta = cfg.get("model_info")
    if not isinstance(meta, dict):
        meta = {}
        cfg["model_info"] = meta
    meta["last_updated"] = _now().strftime("%Y-%m-%d")
    meta["auto_updated_by"] = "daily_report.py wrapper ai pipeline (v2)"
    meta["auto_update_note"] = f"entry_th {cur_th:.2f}->{best['th']:.2f} improve={improve:.4f} window_days={days} min_trades={min_trades}"

    _save_json(AI_MODEL, cfg)
    print(f"[OK] applied to ai_model.json: confidence_threshold.entry {cur_th:.2f} -> {best['th']:.2f}")
    return 0

def run_legacy(argv):
    if not LEGACY.exists():
        print("[NG] legacy daily_report not found:", LEGACY)
        return 2
    sys.argv = [str(LEGACY)] + argv
    runpy.run_path(str(LEGACY), run_name="__main__")
    return 0

def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--legacy", action="store_true", help="run legacy daily_report (pass-through)")
    ap.add_argument("--ai", choices=["train","eval","apply","run"], help="AI pipeline mode")
    ap.add_argument("--days", type=int, default=90, help="lookback window (days)")
    ap.add_argument("--min_trades", type=int, default=80, help="minimum trades required for evaluation")
    ap.add_argument("--verbose", action="store_true", help="print grid evaluation details")
    args, rest = ap.parse_known_args()

    if args.legacy or (args.ai is None):
        return run_legacy(rest)

    mode = args.ai
    if mode in ("train","eval"):
        return ai_train_eval_apply(days=args.days, min_trades=args.min_trades, apply=False, verbose=args.verbose)
    if mode == "apply":
        return ai_train_eval_apply(days=args.days, min_trades=args.min_trades, apply=True, verbose=args.verbose)
    if mode == "run":
        return ai_train_eval_apply(days=args.days, min_trades=args.min_trades, apply=True, verbose=args.verbose)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
