#!/usr/bin/env python3
# ============================================================
# daily_report.py (Wrapper)
#   - legacy daily_report preserved as daily_report_legacy.py
#   - adds AI pipeline: train -> eval -> apply (one-button)
#
# Usage:
#   python3 daily_report.py                 # run legacy behavior
#   python3 daily_report.py --legacy ...    # pass-through legacy
#   python3 daily_report.py --ai train --days 30
#   python3 daily_report.py --ai eval  --days 60
#   python3 daily_report.py --ai apply --days 90 --min_trades 80
#   python3 daily_report.py --ai run   --days 90 --min_trades 80   # train+eval+apply
# ============================================================

from __future__ import annotations
import argparse
import json
import csv
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path
import runpy

MAIN = Path(__file__).resolve().parent
LEGACY = MAIN / "daily_report_legacy.py"
AI_MODEL = MAIN / "ai_model.json"
TUNE_OVERRIDE = MAIN / "tune_override.json"

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

def _find_ai_training_log():
    # priority: MAIN/ai_training_log.csv, then ../logs/ai_training_log.csv
    cands = [
        MAIN / "ai_training_log.csv",
        MAIN.parent / "logs" / "ai_training_log.csv",
    ]
    for p in cands:
        if p.exists():
            return p
    return None

def _iter_ai_rows(path: Path):
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            yield row

def _parse_float(x):
    try:
        if x is None: return None
        s = str(x).strip()
        if s == "": return None
        return float(s)
    except Exception:
        return None

def _parse_time(s: str):
    # expected: "YYYY-MM-DD HH:MM:SS"
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None

def _outcome_bucket(outcome: str) -> str:
    o = (outcome or "").strip().upper()
    # tolerate both: TP/SL/TIMEOUT and PAPER_EXIT_TP...
    if "TP" == o or o.endswith("_TP"):
        return "WIN"
    if "SL" == o or o.endswith("_SL"):
        return "LOSS"
    if "TIMEOUT" == o or o.endswith("_TIMEOUT"):
        return "NEUTRAL"
    if "PARTIAL" in o:
        return "NEUTRAL"
    if "EOD" in o:
        return "NEUTRAL"
    if o == "":
        return "UNKNOWN"
    return "UNKNOWN"

def _load_current_threshold():
    cfg = _load_json(AI_MODEL, {})
    th = cfg.get("confidence_threshold", {})
    try:
        cur = float(th.get("entry", 0.65))
    except Exception:
        cur = 0.65
    return cur, cfg

def _evaluate_threshold(rows, th):
    # rows: list of dict with ai_score and outcome
    # metric: WIN - 2*LOSS - 0.5*NEUTRAL (normalized by trades)
    picked = []
    for r in rows:
        s = r["ai_score"]
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
    p = _find_ai_training_log()
    if not p:
        print("[NG] ai_training_log.csv not found. expected MAIN/ai_training_log.csv or ../logs/ai_training_log.csv")
        return 2

    cutoff = _now() - timedelta(days=int(days))
    rows = []
    for row in _iter_ai_rows(p):
        t = _parse_time(row.get("time",""))
        if not t or t < cutoff:
            continue
        sc = _parse_float(row.get("ai_score"))
        out = row.get("outcome") or row.get("result") or ""
        bucket = _outcome_bucket(out)
        rows.append({"time": t, "ai_score": sc, "outcome": out, "bucket": bucket})

    rows_scored = [r for r in rows if r["ai_score"] is not None and r["bucket"] != "UNKNOWN"]

    print(f"[INFO] ai_log={p}")
    print(f"[INFO] window=last {days} days -> rows={len(rows)} scored_rows={len(rows_scored)}")

    if len(rows_scored) < max(20, min_trades):
        print(f"[NG] not enough scored rows to evaluate safely: {len(rows_scored)} < min_required={max(20, min_trades)}")
        return 2

    cur_th, cfg = _load_current_threshold()
    grid = [round(x, 2) for x in [0.50,0.55,0.60,0.65,0.70,0.75,0.80,0.85]]

    base = _evaluate_threshold(rows_scored, cur_th)
    best = {"th": cur_th, **base}

    if verbose:
        print(f"[BASE] th={cur_th:.2f} -> n={base['n']} win={base['win']} loss={base['loss']} neutral={base['neutral']} metric={base['metric']:.4f}")

    for th in grid:
        ev = _evaluate_threshold(rows_scored, th)
        if ev["n"] < min_trades:
            continue
        cand = {"th": th, **ev}
        if cand["metric"] > best["metric"]:
            best = cand
        if verbose:
            print(f"[GRID] th={th:.2f} -> n={ev['n']} win={ev['win']} loss={ev['loss']} neutral={ev['neutral']} metric={ev['metric']:.4f}")

    print("\n[RESULT]")
    print(f"  current_th={cur_th:.2f} metric={base['metric']:.4f} n={base['n']}")
    print(f"  best_th   ={best['th']:.2f} metric={best['metric']:.4f} n={best['n']} (min_trades={min_trades})")

    # apply only if improvement is meaningful
    improve = best["metric"] - base["metric"]
    if best["th"] == cur_th or improve < 0.02:
        print(f"[INFO] no safe improvement to apply (improve={improve:.4f} < 0.02 or same threshold).")
        return 0

    if not apply:
        print("[INFO] dry-run (no apply). Use: --ai apply or --ai run")
        return 0

    # apply to ai_model.json (only confidence_threshold.entry)
    if not isinstance(cfg, dict):
        cfg = {}
    if "confidence_threshold" not in cfg or not isinstance(cfg.get("confidence_threshold"), dict):
        cfg["confidence_threshold"] = {}
    cfg["confidence_threshold"]["entry"] = float(best["th"])

    # audit meta
    meta = cfg.get("model_info")
    if not isinstance(meta, dict):
        meta = {}
        cfg["model_info"] = meta
    meta["last_updated"] = _now().strftime("%Y-%m-%d")
    meta["auto_updated_by"] = "daily_report.py wrapper ai pipeline"
    meta["auto_update_note"] = f"entry_th {cur_th:.2f}->{best['th']:.2f} improve={improve:.4f} window_days={days} min_trades={min_trades}"

    _save_json(AI_MODEL, cfg)
    print(f"[OK] applied to ai_model.json: confidence_threshold.entry {cur_th:.2f} -> {best['th']:.2f}")

    return 0

def run_legacy(argv):
    if not LEGACY.exists():
        print("[NG] legacy daily_report not found:", LEGACY)
        return 2
    # pass-through legacy execution
    sys.argv = [str(LEGACY)] + argv
    runpy.run_path(str(LEGACY), run_name="__main__")
    return 0

def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--legacy", action="store_true", help="run legacy daily_report (pass-through)")
    ap.add_argument("--ai", choices=["train","eval","apply","run"], help="AI pipeline mode")
    ap.add_argument("--days", type=int, default=90, help="lookback window (days) for ai_training_log.csv")
    ap.add_argument("--min_trades", type=int, default=80, help="minimum trades required for threshold evaluation")
    ap.add_argument("--verbose", action="store_true", help="print grid evaluation details")
    args, rest = ap.parse_known_args()

    # default: run legacy if no ai specified
    if args.legacy or (args.ai is None):
        return run_legacy(rest)

    # ai pipeline
    mode = args.ai
    if mode in ("train","eval"):
        # in this wrapper, train/eval are same operation (search best threshold);
        # 'apply' actually writes the change.
        return ai_train_eval_apply(days=args.days, min_trades=args.min_trades, apply=False, verbose=args.verbose)
    if mode == "apply":
        return ai_train_eval_apply(days=args.days, min_trades=args.min_trades, apply=True, verbose=args.verbose)
    if mode == "run":
        # train+eval+apply in one shot
        return ai_train_eval_apply(days=args.days, min_trades=args.min_trades, apply=True, verbose=args.verbose)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
