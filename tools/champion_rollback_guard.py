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


def run_champion_rollback(args: argparse.Namespace) -> int:
    ai_model_path = _resolve_path(args.ai_model_path)
    state_path = _resolve_path(args.state_path)
    main_logs = _resolve_path(args.main_logs_dir)
    out_dir = _resolve_path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    model = _load_json_dict(ai_model_path)
    model_info = model.get("model_info")
    if not isinstance(model_info, dict):
        model_info = {}
        model["model_info"] = model_info

    promoted_from = model_info.get("champion_challenger_from_threshold")
    promoted_to = model_info.get("champion_challenger_to_threshold")
    current_th = _get_threshold(model)
    if promoted_from is None or promoted_to is None:
        reason = "no_promotion_history"
        print(f"[INFO] champion_rollback skip: {reason}")
        state = _load_json_dict(state_path)
        state["_champion_rollback"] = {
            "updated_at": _now_text(),
            "lookback_days": int(args.lookback_days),
            "reason": reason,
            "rolled_back": False,
        }
        if not args.dry_run:
            _write_json_dict(state_path, state)
        else:
            print(f"[DRYRUN] state update path={state_path}")
        return 0

    from_th = _safe_float(promoted_from, default=0.0)
    to_th = _safe_float(promoted_to, default=0.0)
    if current_th is None or abs(float(current_th) - float(to_th)) > 1e-9:
        reason = "current_threshold_not_promoted_target"
        print(
            "[INFO] champion_rollback skip: {} (current={} promoted_to={})".format(
                reason,
                "None" if current_th is None else f"{float(current_th):.6f}",
                f"{float(to_th):.6f}",
            )
        )
        state = _load_json_dict(state_path)
        state["_champion_rollback"] = {
            "updated_at": _now_text(),
            "lookback_days": int(args.lookback_days),
            "reason": reason,
            "rolled_back": False,
            "current_threshold": (None if current_th is None else round(float(current_th), 6)),
            "promoted_to_threshold": round(float(to_th), 6),
        }
        if not args.dry_run:
            _write_json_dict(state_path, state)
        else:
            print(f"[DRYRUN] state update path={state_path}")
        return 0

    today = date.today()
    end_d = today
    start_d = today - timedelta(days=max(1, int(args.lookback_days)) - 1)
    start8 = _day8(start_d)
    end8 = _day8(end_d)

    rc, out_path, report = _calc_review(main_logs, start8, end8, out_dir / "champion_rollback_main")
    m = _extract_metrics(report)
    closed_n = int(m["closed_n"])
    pf = float(m["profit_factor"])
    avg_ret = float(m["avg_ret_pct"])

    rollback_trigger = (
        closed_n >= int(args.min_closed)
        and (pf < float(args.pf_floor) or avg_ret < float(args.avg_ret_floor))
    )

    print(
        "[INFO] champion_rollback range={} closed={} pf={:.4f} avg_ret={:.4f} trigger={}".format(
            f"{start8}-{end8}",
            closed_n,
            pf,
            avg_ret,
            bool(rollback_trigger),
        )
    )

    reason = "metric_floor" if rollback_trigger else "guard_pass"
    rolled_back = False
    restored_to = None
    if rollback_trigger and bool(args.apply):
        restored_to = _set_threshold(model, float(from_th))
        model_info["champion_rollback_last_at"] = _now_text()
        model_info["champion_rollback_reason"] = reason
        model_info["champion_rollback_lookback_days"] = int(args.lookback_days)
        model_info["champion_rollback_eval_closed_n"] = int(closed_n)
        model_info["champion_rollback_eval_pf"] = round(float(pf), 6)
        model_info["champion_rollback_eval_avg_ret_pct"] = round(float(avg_ret), 6)
        model_info["champion_rollback_pf_floor"] = float(args.pf_floor)
        model_info["champion_rollback_avg_ret_floor"] = float(args.avg_ret_floor)
        model_info["champion_rollback_from_threshold"] = round(float(to_th), 6)
        model_info["champion_rollback_to_threshold"] = round(float(restored_to), 6)

        if args.dry_run:
            print(f"[DRYRUN] rollback threshold: {to_th:.6f} -> {restored_to:.6f}")
        else:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            bak = ai_model_path.with_name(f"{ai_model_path.name}.bak_rollback_{ts}")
            try:
                shutil.copy2(ai_model_path, bak)
                print(f"[OK] backup: {bak}")
            except Exception as e:
                print(f"[WARN] backup failed: {e}")
            _write_json_dict(ai_model_path, model)
            print(f"[OK] rollback threshold: {to_th:.6f} -> {restored_to:.6f}")
        rolled_back = True

    state = _load_json_dict(state_path)
    state["_champion_rollback"] = {
        "updated_at": _now_text(),
        "range_start8": start8,
        "range_end8": end8,
        "lookback_days": int(args.lookback_days),
        "weekly_report_main_path": str(out_path),
        "weekly_report_main_rc": int(rc),
        "metrics": {
            "closed_n": int(closed_n),
            "profit_factor": round(float(pf), 6),
            "avg_ret_pct": round(float(avg_ret), 6),
            "win_rate_pct": round(float(m["win_rate_pct"]), 6),
            "ret_sum_pct": round(float(m["ret_sum_pct"]), 6),
        },
        "gate": {
            "min_closed": int(args.min_closed),
            "pf_floor": float(args.pf_floor),
            "avg_ret_floor": float(args.avg_ret_floor),
            "trigger": bool(rollback_trigger),
        },
        "apply_requested": bool(args.apply),
        "rolled_back": bool(rolled_back),
        "reason": str(reason),
        "from_threshold": round(float(to_th), 6),
        "to_threshold": (round(float(restored_to), 6) if restored_to is not None else round(float(from_th), 6)),
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
            "Monitor champion performance after promotion and rollback threshold "
            "to previous value when metric floor is violated."
        )
    )
    ap.add_argument("--lookback-days", type=int, default=7, help="rolling evaluation window days (default: 7)")
    ap.add_argument("--main-logs-dir", default="../logs", help="main trade_log directory (default: ../logs)")
    ap.add_argument("--out-dir", default="weekly_report_out", help="weekly report output base dir")

    ap.add_argument("--min-closed", type=int, default=20, help="minimum closed trades to evaluate rollback")
    ap.add_argument("--pf-floor", type=float, default=0.95, help="rollback trigger: PF below this floor")
    ap.add_argument("--avg-ret-floor", type=float, default=-0.02, help="rollback trigger: avg_ret_pct below this floor")

    ap.add_argument("--apply", action="store_true", help="apply rollback when trigger is true")
    ap.add_argument("--dry-run", action="store_true", help="do not write files")

    ap.add_argument("--ai-model-path", default="ai_model.json", help="main ai model path")
    ap.add_argument("--state-path", default="state.json", help="state json path")
    return ap


def main() -> None:
    args = build_arg_parser().parse_args()
    try:
        rc = run_champion_rollback(args)
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
