#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import weekly_report  # noqa: E402


def _day8(d: date) -> str:
    return d.strftime("%Y%m%d")


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _resolve_path(p: str) -> Path:
    path = Path(p).expanduser()
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    return path


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return float(default)
        s = str(v).strip()
        if s == "":
            return float(default)
        return float(s)
    except Exception:
        return float(default)


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return int(default)
        return int(float(str(v).strip()))
    except Exception:
        return int(default)


def _load_json_dict(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_json_dict(path: Path, obj: Dict[str, Any]) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _get_threshold(model: Dict[str, Any]) -> Optional[float]:
    g = model.get("global")
    if not isinstance(g, dict):
        return None
    v = g.get("threshold")
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _set_threshold(model: Dict[str, Any], threshold: float) -> float:
    g = model.get("global")
    if not isinstance(g, dict):
        g = {}
        model["global"] = g
    th = float(threshold)
    g["threshold"] = th
    return th


def _calc_review(logs_dir: Path, start8: str, end8: str, out_dir: Path) -> Tuple[int, Path, Dict[str, Any]]:
    args = argparse.Namespace(
        target=f"{start8}-{end8}",
        start=None,
        end=None,
        out_dir=str(out_dir),
        logs_dir=str(logs_dir),
        week_start="MON",
        strict=False,
    )
    return weekly_report.run_weekly_report(args)


def _extract_metrics(report: Dict[str, Any]) -> Dict[str, float]:
    wr = report.get("weekly_review", {}) if isinstance(report, dict) else {}
    if not isinstance(wr, dict):
        wr = {}
    return {
        "closed_n": float(_safe_int(wr.get("closed_n"), 0)),
        "profit_factor": float(_safe_float(wr.get("profit_factor"), 0.0)),
        "avg_ret_pct": float(_safe_float(wr.get("avg_ret_pct"), 0.0)),
        "win_rate_pct": float(_safe_float(wr.get("win_rate_pct"), 0.0)),
        "ret_sum_pct": float(_safe_float(wr.get("ret_sum_pct"), 0.0)),
    }


def _evaluate_gate(main_m: Dict[str, float], shadow_m: Dict[str, float], args: argparse.Namespace) -> Dict[str, Any]:
    main_n = int(main_m.get("closed_n", 0.0))
    shadow_n = int(shadow_m.get("closed_n", 0.0))
    main_pf = float(main_m.get("profit_factor", 0.0))
    shadow_pf = float(shadow_m.get("profit_factor", 0.0))
    main_avg = float(main_m.get("avg_ret_pct", 0.0))
    shadow_avg = float(shadow_m.get("avg_ret_pct", 0.0))

    pf_delta = shadow_pf - main_pf
    avg_delta = shadow_avg - main_avg

    reasons = []
    if main_n < int(args.min_closed):
        reasons.append(f"main_closed<{int(args.min_closed)} ({main_n})")
    if shadow_n < int(args.min_closed):
        reasons.append(f"shadow_closed<{int(args.min_closed)} ({shadow_n})")
    if shadow_pf < float(args.shadow_pf_min):
        reasons.append(f"shadow_pf<{float(args.shadow_pf_min):.4f} ({shadow_pf:.4f})")
    if shadow_avg < float(args.shadow_avg_ret_min):
        reasons.append(f"shadow_avg_ret<{float(args.shadow_avg_ret_min):.4f} ({shadow_avg:.4f})")
    if pf_delta < float(args.min_pf_delta):
        reasons.append(f"pf_delta<{float(args.min_pf_delta):.4f} ({pf_delta:.4f})")
    if avg_delta < float(args.min_avg_ret_delta):
        reasons.append(f"avg_ret_delta<{float(args.min_avg_ret_delta):.4f} ({avg_delta:.4f})")

    return {
        "pass": len(reasons) == 0,
        "reasons": reasons,
        "main": {"closed_n": main_n, "profit_factor": main_pf, "avg_ret_pct": main_avg},
        "shadow": {"closed_n": shadow_n, "profit_factor": shadow_pf, "avg_ret_pct": shadow_avg},
        "delta": {"profit_factor": pf_delta, "avg_ret_pct": avg_delta},
        "gate": {
            "min_closed": int(args.min_closed),
            "shadow_pf_min": float(args.shadow_pf_min),
            "shadow_avg_ret_min": float(args.shadow_avg_ret_min),
            "min_pf_delta": float(args.min_pf_delta),
            "min_avg_ret_delta": float(args.min_avg_ret_delta),
        },
    }


def run_champion_challenger(args: argparse.Namespace) -> int:
    today = date.today()
    end_d = today
    start_d = today - timedelta(days=max(1, int(args.lookback_days)) - 1)
    start8 = _day8(start_d)
    end8 = _day8(end_d)

    out_dir = _resolve_path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    main_logs = _resolve_path(args.main_logs_dir)
    shadow_logs = _resolve_path(args.shadow_logs_dir)
    rc_main, out_main, rep_main = _calc_review(main_logs, start8, end8, out_dir / "champion_main")
    rc_shadow, out_shadow, rep_shadow = _calc_review(shadow_logs, start8, end8, out_dir / "champion_shadow")

    main_metrics = _extract_metrics(rep_main)
    shadow_metrics = _extract_metrics(rep_shadow)
    gate = _evaluate_gate(main_metrics, shadow_metrics, args)

    print(
        "[INFO] champion_gate range={} main(closed={}, pf={:.4f}, avg_ret={:.4f}) "
        "shadow(closed={}, pf={:.4f}, avg_ret={:.4f}) pass={}".format(
            f"{start8}-{end8}",
            int(main_metrics["closed_n"]),
            float(main_metrics["profit_factor"]),
            float(main_metrics["avg_ret_pct"]),
            int(shadow_metrics["closed_n"]),
            float(shadow_metrics["profit_factor"]),
            float(shadow_metrics["avg_ret_pct"]),
            bool(gate["pass"]),
        )
    )
    if gate["reasons"]:
        print("[INFO] gate_reasons: " + "; ".join(str(x) for x in gate["reasons"]))

    state_path = _resolve_path(args.state_path)
    state = _load_json_dict(state_path)
    drift_watch = state.get("_drift_watch")
    drift_status = ""
    if isinstance(drift_watch, dict):
        drift_status = str(drift_watch.get("status", "")).upper()

    ai_main_path = _resolve_path(args.ai_model_path)
    ai_shadow_path = _resolve_path(args.ai_model_shadow_path)
    ai_main = _load_json_dict(ai_main_path)
    ai_shadow = _load_json_dict(ai_shadow_path)
    main_th = _get_threshold(ai_main)
    shadow_th = _get_threshold(ai_shadow)

    promoted = False
    reason = "gate_pass" if bool(gate["pass"]) else "gate_blocked"
    if args.force_promote:
        reason = "force_promote"

    do_apply = bool(args.apply) and (bool(gate["pass"]) or bool(args.force_promote))
    if do_apply and (not args.force_promote) and drift_status == "ALERT":
        do_apply = False
        reason = "drift_alert_block"
        print("[INFO] promotion blocked by drift_watch status=ALERT")
    if do_apply:
        if shadow_th is None:
            reason = "shadow_threshold_missing"
        else:
            from_th = main_th
            to_th = _set_threshold(ai_main, float(shadow_th))
            mi = ai_main.get("model_info")
            if not isinstance(mi, dict):
                mi = {}
                ai_main["model_info"] = mi
            mi["champion_challenger_last_promoted_at"] = _now_text()
            mi["champion_challenger_from_threshold"] = (round(float(from_th), 6) if from_th is not None else None)
            mi["champion_challenger_to_threshold"] = round(float(to_th), 6)
            mi["champion_challenger_lookback_days"] = int(args.lookback_days)
            mi["champion_challenger_main_pf"] = round(float(main_metrics["profit_factor"]), 6)
            mi["champion_challenger_shadow_pf"] = round(float(shadow_metrics["profit_factor"]), 6)
            mi["champion_challenger_main_avg_ret_pct"] = round(float(main_metrics["avg_ret_pct"]), 6)
            mi["champion_challenger_shadow_avg_ret_pct"] = round(float(shadow_metrics["avg_ret_pct"]), 6)
            mi["champion_challenger_gate_pass"] = bool(gate["pass"])
            mi["champion_challenger_reason"] = reason
            if args.dry_run:
                print(
                    "[DRYRUN] promote threshold: {} -> {}".format(
                        "None" if from_th is None else f"{float(from_th):.6f}",
                        f"{float(to_th):.6f}",
                    )
                )
            else:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                bak = ai_main_path.with_name(f"{ai_main_path.name}.bak_champion_{ts}")
                try:
                    shutil.copy2(ai_main_path, bak)
                    print(f"[OK] backup: {bak}")
                except Exception as e:
                    print(f"[WARN] backup failed: {e}")
                _write_json_dict(ai_main_path, ai_main)
                print(
                    "[OK] promoted threshold: {} -> {}".format(
                        "None" if from_th is None else f"{float(from_th):.6f}",
                        f"{float(to_th):.6f}",
                    )
                )
            promoted = True

    state["_champion_challenger"] = {
        "updated_at": _now_text(),
        "range_start8": start8,
        "range_end8": end8,
        "lookback_days": int(args.lookback_days),
        "main_logs_dir": str(main_logs),
        "shadow_logs_dir": str(shadow_logs),
        "weekly_report_main_path": str(out_main),
        "weekly_report_shadow_path": str(out_shadow),
        "weekly_report_main_rc": int(rc_main),
        "weekly_report_shadow_rc": int(rc_shadow),
        "main_metrics": {
            "closed_n": int(main_metrics["closed_n"]),
            "profit_factor": round(float(main_metrics["profit_factor"]), 6),
            "avg_ret_pct": round(float(main_metrics["avg_ret_pct"]), 6),
            "win_rate_pct": round(float(main_metrics["win_rate_pct"]), 6),
            "ret_sum_pct": round(float(main_metrics["ret_sum_pct"]), 6),
        },
        "shadow_metrics": {
            "closed_n": int(shadow_metrics["closed_n"]),
            "profit_factor": round(float(shadow_metrics["profit_factor"]), 6),
            "avg_ret_pct": round(float(shadow_metrics["avg_ret_pct"]), 6),
            "win_rate_pct": round(float(shadow_metrics["win_rate_pct"]), 6),
            "ret_sum_pct": round(float(shadow_metrics["ret_sum_pct"]), 6),
        },
        "gate": gate,
        "apply_requested": bool(args.apply),
        "force_promote": bool(args.force_promote),
        "drift_status": drift_status,
        "promoted": bool(promoted),
        "reason": str(reason),
        "main_threshold_before": (round(float(main_th), 6) if main_th is not None else None),
        "shadow_threshold": (round(float(shadow_th), 6) if shadow_th is not None else None),
    }
    if args.dry_run:
        print(f"[DRYRUN] state update path={state_path}")
    else:
        _write_json_dict(state_path, state)
        print(f"[OK] state updated path={state_path}")

    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=(
            "Compare champion(main) and challenger(shadow) performance on rolling window, "
            "and optionally promote shadow threshold into ai_model.json."
        )
    )
    ap.add_argument("--lookback-days", type=int, default=14, help="rolling evaluation window days (default: 14)")
    ap.add_argument("--main-logs-dir", default="../logs", help="main trade_log directory (default: ../logs)")
    ap.add_argument("--shadow-logs-dir", default="../logs/instances/shadow", help="shadow trade_log directory")
    ap.add_argument("--out-dir", default="weekly_report_out", help="weekly report output base dir")

    ap.add_argument("--min-closed", type=int, default=20, help="minimum closed trades for both main/shadow")
    ap.add_argument("--shadow-pf-min", type=float, default=1.00, help="minimum shadow profit factor")
    ap.add_argument("--shadow-avg-ret-min", type=float, default=0.0, help="minimum shadow avg return (%)")
    ap.add_argument("--min-pf-delta", type=float, default=0.03, help="minimum (shadow_pf - main_pf)")
    ap.add_argument("--min-avg-ret-delta", type=float, default=0.01, help="minimum (shadow_avg_ret - main_avg_ret)")

    ap.add_argument("--apply", action="store_true", help="apply promotion when gate passes")
    ap.add_argument("--force-promote", action="store_true", help="apply promotion even when gate fails")
    ap.add_argument("--dry-run", action="store_true", help="do not write files")

    ap.add_argument("--ai-model-path", default="ai_model.json", help="main ai model path")
    ap.add_argument("--ai-model-shadow-path", default="ai_model_shadow.json", help="shadow ai model path")
    ap.add_argument("--state-path", default="state.json", help="state json path")
    return ap


def main() -> None:
    args = build_arg_parser().parse_args()
    try:
        rc = run_champion_challenger(args)
    except ValueError as e:
        print(f"[ERROR] {e}")
        sys.exit(2)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        sys.exit(2)
    except Exception as e:
        print(f"[ERROR] fatal: {e}")
        sys.exit(2)
    sys.exit(rc)


if __name__ == "__main__":
    main()
