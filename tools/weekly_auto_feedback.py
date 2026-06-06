#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import weekly_report  # noqa: E402
from tools.llm_provider import normalize_openai_base_url, run_openai_responses_summary  # noqa: E402
from tools.trade_event_notifier import _build_daily_trade_review  # noqa: E402


WEEKDAY_CHOICES = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
OLLAMA_BASE_URL_DEFAULT = os.getenv("OUROBOROS_OLLAMA_BASE_URL", os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
OLLAMA_MODEL_DEFAULT = os.getenv("OUROBOROS_OLLAMA_MODEL", os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b"))
OLLAMA_TIMEOUT_SEC_DEFAULT = 180
OLLAMA_MAX_CHARS_DEFAULT = 1200
OPENAI_BASE_URL_DEFAULT = os.getenv("OUROBOROS_OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL_DEFAULT = os.getenv("OUROBOROS_OPENAI_MODEL", "gpt-5.4-mini")
OPENAI_API_KEY_ENV_DEFAULT = os.getenv("OUROBOROS_OPENAI_API_KEY_ENV", "OPENAI_API_KEY")
OPENAI_MAX_OUTPUT_TOKENS_DEFAULT = 420
MODEL_SIZE_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*b", re.IGNORECASE)


def _normalize_base_url(base_url: str) -> str:
    s = str(base_url or "").strip()
    if not s:
        return "http://127.0.0.1:11434"
    return s.rstrip("/")


def _http_get_json(url: str, timeout_sec: int) -> Dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=float(timeout_sec)) as resp:
        raw = resp.read()
    text = raw.decode("utf-8", errors="replace")
    d = json.loads(text)
    if not isinstance(d, dict):
        raise ValueError(f"invalid JSON object from {url}")
    return d


def _http_post_json(url: str, payload: Dict[str, Any], timeout_sec: int) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=float(timeout_sec)) as resp:
        raw = resp.read()
    text = raw.decode("utf-8", errors="replace")
    d = json.loads(text)
    if not isinstance(d, dict):
        raise ValueError(f"invalid JSON object from {url}")
    return d


def _read_toml_val(path: Path, key: str) -> str:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(key):
                v = line.split("=", 1)[1].strip().strip('"').strip("'")
                return v if v not in ("", "***MASKED***") else ""
    except Exception:
        pass
    return ""


def _ntfy_post_text(url: str, bearer: str, body: str, title: str) -> bool:
    if not url:
        return False
    try:
        headers: Dict[str, str] = {
            "Content-Type": "text/plain; charset=utf-8",
            "Title": title,
            "Tags": "bar_chart",
            "Priority": "default",
        }
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        req = urllib.request.Request(url, data=body.encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=5.0) as r:
            return r.status < 300
    except Exception:
        return False


def _run_sweep_and_notify(
    control_path: Path,
    secrets_path: Path,
    *,
    min_bars: int = 1000,
    min_pf_improve: float = 0.10,
    dry_run: bool = False,
) -> None:
    """Run TP/SL sweep after weekly autotrain and notify if a better combo is found."""
    import subprocess
    import re as _re

    ohlc_path = ROOT / "data" / "historical_ohlc.csv"
    if not ohlc_path.exists():
        print("[sweep] OHLC data not found, skip")
        return

    try:
        bar_count = sum(1 for _ in open(ohlc_path)) - 1  # subtract header
    except Exception:
        bar_count = 0
    if bar_count < min_bars:
        print(f"[sweep] OHLC bars={bar_count} < {min_bars}, skip")
        return

    # Read current TP/SL from CONTROL
    ctrl: Dict[str, str] = {}
    try:
        for line in control_path.read_text().splitlines():
            parts = line.split(",", 1)
            if len(parts) == 2:
                ctrl[parts[0].strip()] = parts[1].strip().strip('"')
    except Exception:
        return

    try:
        current_tp = float(ctrl.get("tp_buy_pct", "0.190"))
        current_sl = float(ctrl.get("sl_pct", "0.140"))
    except ValueError:
        return

    print(f"[sweep] running TP/SL sweep (bars={bar_count}) current TP={current_tp} SL={current_sl}")
    try:
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "run_backtest.py"),
             "--sweep", "--ohlc", str(ohlc_path)],
            capture_output=True, text=True, timeout=180,
        )
        out = result.stdout + result.stderr
    except Exception as e:
        print(f"[sweep] failed: {e}")
        return

    # Parse best result line: "推奨: tp_buy_pct=X.XXX  sl_pct=X.XXX  (PF=X.XXX  WR=XX.X%  n=XX)"
    best_tp = best_sl = best_pf = best_n = None
    m = _re.search(r"推奨.*tp_buy_pct=([\d.]+)\s+sl_pct=([\d.]+)\s+\(PF=([\d.]+).*n=(\d+)", out)
    if m:
        try:
            best_tp = float(m.group(1))
            best_sl = float(m.group(2))
            best_pf = float(m.group(3))
            best_n = int(m.group(4))
        except Exception:
            pass

    if best_pf is None:
        print("[sweep] could not parse best result")
        return

    # Compute current PF from sweep output
    current_line = _re.search(
        rf"{current_tp:.3f}\s+{current_sl:.3f}\s+\d+\s+[\d.]+\s+([\d.]+)", out
    )
    current_pf = float(current_line.group(1)) if current_line else None

    improve = best_pf - (current_pf or 0.0)
    print(f"[sweep] best TP={best_tp} SL={best_sl} PF={best_pf:.3f} (n={best_n})  current_pf={current_pf}  improve={improve:+.3f}")

    if improve < min_pf_improve:
        print(f"[sweep] improvement {improve:+.3f} < threshold {min_pf_improve:.2f}, no notification")
        return

    if best_n < 30:
        print(f"[sweep] best_n={best_n} < 30, sample count too small, skip notification")
        return

    # Send ntfy
    ntfy_url = _read_toml_val(secrets_path, "ntfy_topic_url")
    ntfy_bearer = _read_toml_val(secrets_path, "ntfy_bearer_token")
    body = (
        f"📈 TP/SL パラメータ更新候補\n"
        f"現行: TP={current_tp:.3f}% SL={current_sl:.3f}%  PF≈{current_pf:.3f}\n"
        f"推奨: TP={best_tp:.3f}% SL={best_sl:.3f}%  PF={best_pf:.3f}  改善={improve:+.3f}\n"
        f"n={best_n}件  ※CONTROL書込はしていません。/backtest で確認後に手動設定してください。"
    )
    if dry_run:
        print(f"[sweep][dry-run] would send ntfy:\n{body}")
        return
    ok = _ntfy_post_text(ntfy_url, ntfy_bearer, body, "Ouroboros Sweep Result")
    print(f"[sweep] ntfy {'sent' if ok else 'failed'}")


def _float_text(v: Any, nd: int = 4) -> str:
    try:
        return f"{float(v):.{nd}f}"
    except Exception:
        return "-"


def _int_text(v: Any) -> str:
    try:
        return str(int(v))
    except Exception:
        return "-"


def _hours_text(v: Any) -> str:
    if isinstance(v, list):
        vals: List[str] = []
        for x in v:
            try:
                vals.append(str(int(x)))
            except Exception:
                continue
        return ",".join(vals) if vals else "-"
    s = str(v or "").strip()
    return s if s else "-"


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


def _extract_weekly_metrics(report: Dict[str, Any]) -> Dict[str, float]:
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


def _build_ai_log_hour_stats(ai_log_path: Path, lookback_days: int = 28) -> str:
    """Return hourly WR summary text from ai_training_log.csv for LLM context."""
    if not ai_log_path.exists():
        return ""
    cutoff = (datetime.now() - timedelta(days=lookback_days)).date()
    hour_n: Dict[int, int] = {}
    hour_tp: Dict[int, int] = {}
    try:
        with ai_log_path.open(encoding="utf-8", errors="ignore") as f:
            for row in csv.DictReader(f):
                t = (row.get("entry_time") or row.get("exit_time") or "")
                if len(t) < 13:
                    continue
                try:
                    entry_dt = datetime.strptime(t[:16], "%Y-%m-%d %H:%M")
                    if entry_dt.date() < cutoff:
                        continue
                    h = entry_dt.hour
                except ValueError:
                    continue
                ret = 0.0
                try:
                    ret = float(row.get("ret_pct") or 0)
                except ValueError:
                    pass
                outcome = str(row.get("outcome", "")).strip().upper()
                is_win = outcome in ("TP", "WIN") or (outcome not in ("SL", "LOSS") and ret > 0)
                is_trade = outcome in ("TP", "WIN", "SL", "LOSS") or abs(ret) > 0.000001
                if not is_trade:
                    continue
                hour_n[h] = hour_n.get(h, 0) + 1
                if is_win:
                    hour_tp[h] = hour_tp.get(h, 0) + 1
    except Exception:
        return ""
    if not hour_n:
        return ""
    lines = []
    for h in sorted(hour_n.keys()):
        n = hour_n[h]
        tp = hour_tp.get(h, 0)
        wr = tp / n * 100
        lines.append(f"  {h:02d}h WR={wr:.0f}% N={n}")
    return f"ai_training_hourly_wr (過去{lookback_days}日):\n" + "\n".join(lines)


def _iter_day8_range(start8: str, end8: str) -> List[str]:
    try:
        start_d = datetime.strptime(str(start8), "%Y%m%d").date()
        end_d = datetime.strptime(str(end8), "%Y%m%d").date()
    except Exception:
        return []
    if end_d < start_d:
        return []
    out: List[str] = []
    cur = start_d
    while cur <= end_d:
        out.append(cur.strftime("%Y%m%d"))
        cur += timedelta(days=1)
    return out


def _build_weekly_pattern_summary(logs_dir: Path, start8: str, end8: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "available": False,
        "day_count": 0,
        "closed_n": 0,
        "loss_patterns": {
            "reversal": 0,
            "weak_follow_through": 0,
            "late_entry": 0,
            "other": 0,
        },
        "opportunity_patterns": {
            "entry_unfilled": 0,
            "exit_unfilled": 0,
            "news_avoidance": 0,
            "time_block": 0,
            "spread_block": 0,
        },
        "dominant_loss_pattern": "-",
        "dominant_opportunity_pattern": "-",
    }
    for day8 in _iter_day8_range(start8, end8):
        review = _build_daily_trade_review(logs_dir, day8)
        if not review:
            continue
        out["day_count"] = int(out["day_count"]) + 1
        out["closed_n"] = int(out["closed_n"]) + int(_safe_int(review.get("closed_n"), 0))
        for key in ("reversal", "weak_follow_through", "late_entry", "other"):
            out["loss_patterns"][key] = int(out["loss_patterns"][key]) + int(
                _safe_int((review.get("loss_pattern_breakdown") or {}).get(key), 0)
            )
        for key in ("entry_unfilled", "exit_unfilled", "news_avoidance", "time_block", "spread_block"):
            out["opportunity_patterns"][key] = int(out["opportunity_patterns"][key]) + int(
                _safe_int((review.get("opportunity_pattern_breakdown") or {}).get(key), 0)
            )
    dominant_loss = max(
        list((out.get("loss_patterns") or {}).items()),
        key=lambda item: int(_safe_int(item[1], 0)),
        default=("", 0),
    )
    dominant_opp = max(
        list((out.get("opportunity_patterns") or {}).items()),
        key=lambda item: int(_safe_int(item[1], 0)),
        default=("", 0),
    )
    out["dominant_loss_pattern"] = str(dominant_loss[0] or "-")
    out["dominant_opportunity_pattern"] = str(dominant_opp[0] or "-")
    out["available"] = bool(int(out["day_count"]) > 0 or int(out["closed_n"]) > 0)
    return out


def _build_shadow_weekly_review(
    *,
    main_report: Dict[str, Any],
    shadow_report: Optional[Dict[str, Any]] = None,
    main_pattern_summary: Optional[Dict[str, Any]] = None,
    shadow_pattern_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    review: Dict[str, Any] = {
        "available": False,
        "decision": "評価保留",
        "reason": "shadow report unavailable",
    }
    if not isinstance(shadow_report, dict) or not shadow_report:
        return review

    main_m = _extract_weekly_metrics(main_report)
    shadow_m = _extract_weekly_metrics(shadow_report)
    main_n = int(main_m["closed_n"])
    shadow_n = int(shadow_m["closed_n"])
    pf_delta = float(shadow_m["profit_factor"] - main_m["profit_factor"])
    avg_delta = float(shadow_m["avg_ret_pct"] - main_m["avg_ret_pct"])
    ret_delta = float(shadow_m["ret_sum_pct"] - main_m["ret_sum_pct"])
    win_delta = float(shadow_m["win_rate_pct"] - main_m["win_rate_pct"])

    decision = "保留"
    if main_n < 10 or shadow_n < 10:
        decision = "評価保留"
        reason = f"main_closed={main_n}, shadow_closed={shadow_n} でサンプル不足"
    elif (
        shadow_m["profit_factor"] >= 1.0
        and pf_delta >= 0.05
        and avg_delta >= 0.003
        and ret_delta >= 0.0
    ):
        decision = "昇格候補"
        reason = (
            f"shadow PF差={pf_delta:+.4f}, avg_ret差={avg_delta:+.4f}, "
            f"ret_sum差={ret_delta:+.4f}, win_rate差={win_delta:+.2f}"
        )
    elif (
        shadow_m["profit_factor"] < 0.9
        or pf_delta <= -0.10
        or avg_delta <= -0.010
        or ret_delta <= -0.10
    ):
        decision = "差し戻し"
        reason = (
            f"shadow PF差={pf_delta:+.4f}, avg_ret差={avg_delta:+.4f}, "
            f"ret_sum差={ret_delta:+.4f}, win_rate差={win_delta:+.2f}"
        )
    else:
        reason = (
            f"shadow PF差={pf_delta:+.4f}, avg_ret差={avg_delta:+.4f}, "
            f"ret_sum差={ret_delta:+.4f}, win_rate差={win_delta:+.2f}"
        )

    review.update(
        {
            "available": True,
            "decision": decision,
            "reason": reason,
            "main": {
                "closed_n": main_n,
                "profit_factor": round(float(main_m["profit_factor"]), 6),
                "avg_ret_pct": round(float(main_m["avg_ret_pct"]), 6),
                "win_rate_pct": round(float(main_m["win_rate_pct"]), 6),
                "ret_sum_pct": round(float(main_m["ret_sum_pct"]), 6),
            },
            "shadow": {
                "closed_n": shadow_n,
                "profit_factor": round(float(shadow_m["profit_factor"]), 6),
                "avg_ret_pct": round(float(shadow_m["avg_ret_pct"]), 6),
                "win_rate_pct": round(float(shadow_m["win_rate_pct"]), 6),
                "ret_sum_pct": round(float(shadow_m["ret_sum_pct"]), 6),
            },
            "delta": {
                "profit_factor": round(float(pf_delta), 6),
                "avg_ret_pct": round(float(avg_delta), 6),
                "win_rate_pct": round(float(win_delta), 6),
                "ret_sum_pct": round(float(ret_delta), 6),
            },
        }
    )
    pattern_hint = "差分小"
    pattern_reason = ""
    if isinstance(main_pattern_summary, dict) and isinstance(shadow_pattern_summary, dict):
        main_loss = main_pattern_summary.get("loss_patterns") if isinstance(main_pattern_summary.get("loss_patterns"), dict) else {}
        shadow_loss = shadow_pattern_summary.get("loss_patterns") if isinstance(shadow_pattern_summary.get("loss_patterns"), dict) else {}
        main_opp = main_pattern_summary.get("opportunity_patterns") if isinstance(main_pattern_summary.get("opportunity_patterns"), dict) else {}
        shadow_opp = shadow_pattern_summary.get("opportunity_patterns") if isinstance(shadow_pattern_summary.get("opportunity_patterns"), dict) else {}
        late_delta = int(_safe_int(shadow_loss.get("late_entry"), 0)) - int(_safe_int(main_loss.get("late_entry"), 0))
        rev_delta = int(_safe_int(shadow_loss.get("reversal"), 0)) - int(_safe_int(main_loss.get("reversal"), 0))
        weak_delta = int(_safe_int(shadow_loss.get("weak_follow_through"), 0)) - int(_safe_int(main_loss.get("weak_follow_through"), 0))
        exec_delta = (
            int(_safe_int(shadow_opp.get("entry_unfilled"), 0))
            + int(_safe_int(shadow_opp.get("exit_unfilled"), 0))
            - int(_safe_int(main_opp.get("entry_unfilled"), 0))
            - int(_safe_int(main_opp.get("exit_unfilled"), 0))
        )
        if decision == "評価保留":
            pattern_hint = "判断保留"
            pattern_reason = "closed サンプル不足で型差分の昇格判断は保留"
        elif exec_delta >= 2:
            pattern_hint = "執行品質不足"
            pattern_reason = f"entry/exit_unfilled 差が {exec_delta:+d}"
        elif late_delta >= 2:
            pattern_hint = "entry品質不足"
            pattern_reason = f"late_entry 差が {late_delta:+d}"
        elif rev_delta >= 2:
            pattern_hint = "逃がし不足"
            pattern_reason = f"reversal 差が {rev_delta:+d}"
        elif weak_delta >= 2:
            pattern_hint = "伸び不足"
            pattern_reason = f"weak_follow_through 差が {weak_delta:+d}"
        elif decision == "昇格候補":
            pattern_hint = "昇格阻害小"
            pattern_reason = "型差分でも大きな悪化が見えない"
        else:
            pattern_reason = (
                f"late={late_delta:+d}, reversal={rev_delta:+d}, "
                f"weak={weak_delta:+d}, exec={exec_delta:+d}"
            )
        review["pattern_hint"] = pattern_hint
        review["pattern_reason"] = pattern_reason
        review["main_patterns"] = dict(main_pattern_summary)
        review["shadow_patterns"] = dict(shadow_pattern_summary)
    return review


def _is_ollama_model_match(installed: str, requested: str) -> bool:
    i = str(installed or "").strip()
    r = str(requested or "").strip()
    if not i or not r:
        return False
    if i == r:
        return True
    if i.startswith(r + ":") or r.startswith(i + ":"):
        return True
    return i.split(":", 1)[0] == r.split(":", 1)[0]


def _ollama_list_models(base_url: str, timeout_sec: int) -> List[str]:
    data = _http_get_json(f"{_normalize_base_url(base_url)}/api/tags", timeout_sec=timeout_sec)
    models = data.get("models")
    if not isinstance(models, list):
        return []
    out: List[str] = []
    for m in models:
        if not isinstance(m, dict):
            continue
        name = str(m.get("name", "")).strip()
        if name:
            out.append(name)
    return out


def _model_size_score(model_name: str) -> float:
    s = str(model_name or "").strip()
    m = MODEL_SIZE_RE.search(s)
    if not m:
        return 9999.0
    try:
        return float(m.group(1))
    except Exception:
        return 9999.0


def _unique_keep_order(items: List[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for x in items:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _get_days_between(start8: str, end8: str) -> List[str]:
    """Return list of YYYYMMDD strings from start8 to end8 inclusive."""
    try:
        s = datetime.strptime(start8, "%Y%m%d")
        e = datetime.strptime(end8, "%Y%m%d")
    except (ValueError, TypeError):
        return []
    out: List[str] = []
    cur = s
    while cur <= e:
        out.append(cur.strftime("%Y%m%d"))
        cur += timedelta(days=1)
    return out


def _build_weekly_llm_prompt(
    *,
    report: Dict[str, Any],
    suggested: Dict[str, str],
    control_changed: Dict[str, Dict[str, str]],
    drift_status: str,
    shadow_weekly_review: Optional[Dict[str, Any]] = None,
    ai_log_hour_text: str = "",
    shadow_sl_cls: Optional[Dict[str, Any]] = None,
) -> str:
    wr = report.get("weekly_review") if isinstance(report.get("weekly_review"), dict) else {}
    ai = report.get("ai_feedback") if isinstance(report.get("ai_feedback"), dict) else {}
    rng = report.get("range") if isinstance(report.get("range"), dict) else {}

    closed_n = _int_text(wr.get("closed_n"))
    win_rate = _float_text(wr.get("win_rate_pct"), 2)
    pf = _float_text(wr.get("profit_factor"), 4)
    avg_ret = _float_text(wr.get("avg_ret_pct"), 4)
    ret_sum = _float_text(wr.get("ret_sum_pct"), 4)
    good_hours = _hours_text(ai.get("good_hours"))
    bad_hours = _hours_text(ai.get("bad_hours"))
    start8 = str(rng.get("start8", "-"))
    end8 = str(rng.get("end8", "-"))

    changed_lines: List[str] = []
    for k in sorted(control_changed.keys()):
        ch = control_changed.get(k, {})
        changed_lines.append(f"- {k}: {ch.get('before', '')} -> {ch.get('after', '')}")
    changed_text = "\n".join(changed_lines) if changed_lines else "- 変更なし"

    suggested_lines = [f"- {k}={v}" for k, v in sorted(suggested.items())]
    suggested_text = "\n".join(suggested_lines) if suggested_lines else "- 提案なし"
    suggested_n = len(suggested_lines)
    changed_n = len(changed_lines)
    shadow_decision = "-"
    shadow_reason = "-"
    shadow_main_text = "-"
    shadow_shadow_text = "-"
    shadow_delta_text = "-"
    shadow_pattern_hint = "-"
    shadow_pattern_reason = "-"
    if isinstance(shadow_weekly_review, dict) and shadow_weekly_review.get("available"):
        main_cmp = shadow_weekly_review.get("main", {}) if isinstance(shadow_weekly_review.get("main"), dict) else {}
        shadow_cmp = shadow_weekly_review.get("shadow", {}) if isinstance(shadow_weekly_review.get("shadow"), dict) else {}
        delta_cmp = shadow_weekly_review.get("delta", {}) if isinstance(shadow_weekly_review.get("delta"), dict) else {}
        shadow_decision = str(shadow_weekly_review.get("decision", "-"))
        shadow_reason = str(shadow_weekly_review.get("reason", "-"))
        shadow_main_text = (
            f"close={int(_safe_int(main_cmp.get('closed_n'), 0))} / "
            f"PF={float(_safe_float(main_cmp.get('profit_factor'), 0.0)):.4f} / "
            f"avg_ret={float(_safe_float(main_cmp.get('avg_ret_pct'), 0.0)):.4f}"
        )
        shadow_shadow_text = (
            f"close={int(_safe_int(shadow_cmp.get('closed_n'), 0))} / "
            f"PF={float(_safe_float(shadow_cmp.get('profit_factor'), 0.0)):.4f} / "
            f"avg_ret={float(_safe_float(shadow_cmp.get('avg_ret_pct'), 0.0)):.4f}"
        )
        shadow_delta_text = (
            f"PF差={float(_safe_float(delta_cmp.get('profit_factor'), 0.0)):+.4f} / "
            f"avg_ret差={float(_safe_float(delta_cmp.get('avg_ret_pct'), 0.0)):+.4f} / "
            f"ret_sum差={float(_safe_float(delta_cmp.get('ret_sum_pct'), 0.0)):+.4f}"
        )
        shadow_pattern_hint = str(shadow_weekly_review.get("pattern_hint", "-"))
        shadow_pattern_reason = str(shadow_weekly_review.get("pattern_reason", "-"))

    return (
        "あなたはOuroborosの運用レビュー担当です。"
        "以下のデータだけを根拠に、簡潔な実務メモを書いてください。\n"
        "出力ルール:\n"
        "- ちょうど5行\n"
        "- 各行は必ず次のラベルで開始: 総評:, 良かった点:, 悪かった点:, 次アクション:, リスク:\n"
        "- 各行に数値(例: PF=..., 勝率=...%)を最低1つ含める\n"
        "- 各行は1文で、45-100文字程度を目安にする\n"
        "- 『1行』『2行』『禁止』などのテンプレ語は書かない\n"
        "- 前置きや補足説明は書かない\n\n"
        "判断ヒント:\n"
        "- closed_n<10 の週はサンプル薄めとして慎重に書く\n"
        "- PF<1.0 または avg_ret_pct<0 なら弱め、PF>=1.0 かつ avg_ret_pct>0 なら強め\n"
        "- bad_hours がある場合は悪かった点と次アクションで優先して触れる\n"
        "- drift_status!=NORMAL の場合はリスク行で再開慎重を明示する\n"
        "- suggested_control_updates が空なら現設定維持寄りに書く\n\n"
        "- shadow_weekly_decision があれば、次アクションかリスクで 昇格候補 / 保留 / 差し戻し に触れる\n\n"
        "- shadow_pattern_hint があれば、昇格前に何が足りないかを次アクションかリスクで触れる\n\n"
        "- shadow_sl_reversal_wrap_pct が50%超の場合はエントリー精度低下（方向ミス多発）を悪かった点か次アクションで明示する\n\n"
        f"対象週: {start8}-{end8}\n"
        f"closed_n: {closed_n}\n"
        f"win_rate_pct: {win_rate}\n"
        f"profit_factor: {pf}\n"
        f"avg_ret_pct: {avg_ret}\n"
        f"ret_sum_pct: {ret_sum}\n"
        f"good_hours: {good_hours}\n"
        f"bad_hours: {bad_hours}\n"
        f"suggested_count: {suggested_n}\n"
        f"changed_count: {changed_n}\n"
        f"drift_status: {drift_status}\n\n"
        f"shadow_weekly_decision: {shadow_decision}\n"
        f"shadow_weekly_reason: {shadow_reason}\n"
        f"shadow_weekly_main: {shadow_main_text}\n"
        f"shadow_weekly_shadow: {shadow_shadow_text}\n"
        f"shadow_weekly_delta: {shadow_delta_text}\n\n"
        f"shadow_pattern_hint: {shadow_pattern_hint}\n"
        f"shadow_pattern_reason: {shadow_pattern_reason}\n\n"
        + (
            f"shadow_sl_classification: total={_safe_int(shadow_sl_cls.get('sl_n'), 0)} "
            f"reversal_wrap={_safe_int(shadow_sl_cls.get('reversal_wrap_n'), 0)}({_safe_float(shadow_sl_cls.get('reversal_wrap_pct'), 0.0):.1f}%) "
            f"profit_miss={_safe_int(shadow_sl_cls.get('profit_miss_n'), 0)}({_safe_float(shadow_sl_cls.get('profit_miss_pct'), 0.0):.1f}%) "
            f"middle={_safe_int(shadow_sl_cls.get('middle_n'), 0)}\n\n"
            if isinstance(shadow_sl_cls, dict) and shadow_sl_cls.get("sl_n", 0)
            else ""
        )
        + "suggested_control_updates:\n"
        f"{suggested_text}\n\n"
        "control_changed (今回実際に変わった値):\n"
        f"{changed_text}\n"
        + (f"\n{ai_log_hour_text}\n" if ai_log_hour_text else "")
    )


def _build_fallback_weekly_summary(
    *,
    report: Dict[str, Any],
    suggested: Dict[str, str],
    drift_status: str,
    shadow_weekly_review: Optional[Dict[str, Any]] = None,
) -> str:
    wr = report.get("weekly_review") if isinstance(report.get("weekly_review"), dict) else {}
    ai = report.get("ai_feedback") if isinstance(report.get("ai_feedback"), dict) else {}

    closed_n = _int_text(wr.get("closed_n"))
    pf = _float_text(wr.get("profit_factor"), 4)
    win_rate = _float_text(wr.get("win_rate_pct"), 2)
    avg_ret = _float_text(wr.get("avg_ret_pct"), 4)
    ret_sum = _float_text(wr.get("ret_sum_pct"), 4)
    good_hours = _hours_text(ai.get("good_hours"))
    bad_hours = _hours_text(ai.get("bad_hours"))

    good_csv = str(suggested.get("ai_train_weekly_good_hours", "")).strip() or good_hours
    bad_csv = str(suggested.get("ai_train_weekly_bad_hours", "")).strip() or bad_hours

    score = "中立"
    try:
        if float(pf) >= 1.0 and float(avg_ret) > 0:
            score = "強め"
        elif float(pf) < 0.9 or float(avg_ret) < 0:
            score = "弱め"
    except Exception:
        pass

    shadow_decision = str((shadow_weekly_review or {}).get("decision", "-"))
    shadow_reason = str((shadow_weekly_review or {}).get("reason", "-"))
    shadow_pattern_hint = str((shadow_weekly_review or {}).get("pattern_hint", "-"))
    shadow_pattern_reason = str((shadow_weekly_review or {}).get("pattern_reason", "-"))
    next_action = (
        f"ai_train_weekly_good_hours={good_csv}, ai_train_weekly_bad_hours={bad_csv} を維持して再検証。"
    )
    risk_line = f"drift_status={drift_status} の間はPF={pf}悪化に注意し、ロット拡大を抑制。"
    if shadow_decision not in ("-", ""):
        next_action = (
            f"shadow判定={shadow_decision}, 型差分={shadow_pattern_hint} を踏まえ、good={good_csv} / bad={bad_csv} を軸に翌週も比較継続。"
        )
        risk_line = f"drift_status={drift_status}, shadow={shadow_decision} ({shadow_reason}), 型差分={shadow_pattern_hint} ({shadow_pattern_reason}) を踏まえ拙速な昇格を避ける。"

    lines = [
        f"総評: closed_n={closed_n}, PF={pf}, 勝率={win_rate}% で週次評価は{score}。",
        f"良かった点: good_hours={good_hours} で比較優位の時間帯が確認できた。",
        f"悪かった点: bad_hours={bad_hours}, ret_sum={ret_sum}%, avg_ret={avg_ret}% が重し。",
        f"次アクション: {next_action}",
        f"リスク: {risk_line}",
    ]
    return "\n".join(lines)


def _is_low_quality_llm_summary(text: str) -> bool:
    s = str(text or "").strip()
    if len(s) < 40:
        return True
    placeholder_tokens = ("1行", "2行", "3行", "4行", "5行", "禁止", "出力形式")
    if any(tok in s for tok in placeholder_tokens):
        return True
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    if len(lines) < 3:
        return True
    labels = ("総評:", "良かった点:", "悪かった点:", "次アクション:", "リスク:")
    labeled = sum(1 for ln in lines if any(ln.startswith(lb) for lb in labels))
    if labeled < 3:
        return True
    if not re.search(r"\d", s):
        return True
    return False


def _run_ollama_weekly_summary(
    *,
    base_url: str,
    model: str,
    prompt: str,
    timeout_sec: int,
    max_chars: int,
) -> str:
    data = _http_post_json(
        f"{_normalize_base_url(base_url)}/api/generate",
        payload={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 180,
            },
        },
        timeout_sec=timeout_sec,
    )
    text = str(data.get("response", "")).strip()
    if not text:
        raise ValueError("empty response from ollama")
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars].rstrip() + "..."
    return text


def _day8(d: date) -> str:
    return d.strftime("%Y%m%d")


def _now_jst_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _resolve_path(p: str) -> Path:
    path = Path(p).expanduser()
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    return path


def _resolve_auto_range(mode: str, today: Optional[date] = None) -> Tuple[str, str]:
    base = today or date.today()
    if mode == "last7":
        end_d = base
        start_d = end_d - timedelta(days=6)
        return _day8(start_d), _day8(end_d)

    # previous-week (MON-SUN)
    this_monday = base - timedelta(days=base.weekday())
    start_d = this_monday - timedelta(days=7)
    end_d = this_monday - timedelta(days=1)
    return _day8(start_d), _day8(end_d)


def _load_control_rows(path: Path) -> List[List[str]]:
    if not path.exists():
        raise FileNotFoundError(f"control file not found: {path}")
    with path.open("r", encoding="utf-8", newline="") as f:
        return [list(r) for r in csv.reader(f)]


def _write_control_rows(path: Path, rows: List[List[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerows(rows)


def _apply_control_updates_to_rows(
    rows: List[List[str]],
    updates: Dict[str, str],
) -> Tuple[List[List[str]], Dict[str, Dict[str, str]]]:
    out = [list(r) for r in rows]
    key_to_idx: Dict[str, int] = {}
    for i, row in enumerate(out):
        if not row:
            continue
        key = str(row[0]).strip()
        if not key or key.startswith("#"):
            continue
        if key not in key_to_idx:
            key_to_idx[key] = i

    changed: Dict[str, Dict[str, str]] = {}
    for key in sorted(updates.keys()):
        new_v = str(updates[key])
        if key in key_to_idx:
            idx = key_to_idx[key]
            row = out[idx]
            old_v = str(row[1]) if len(row) >= 2 else ""
            if old_v != new_v:
                if len(row) >= 2:
                    row[1] = new_v
                else:
                    row.append(new_v)
                changed[key] = {"before": old_v, "after": new_v}
        else:
            out.append([key, new_v])
            changed[key] = {"before": "", "after": new_v}
    return out, changed


def _analyze_fast_ma_filter(
    logs_dir: Path,
    lookback_days: int = 14,
) -> Dict[str, Any]:
    """Analyze fast_ma_near filter dominance and suggest parameter review if needed.

    Returns a dict with per-day stats and a recommendation flag.
    """
    import csv as _csv
    from datetime import date, timedelta

    today = date.today()
    day_stats = []
    total_ok = total_ma = total_tw = total_ai = 0

    for i in range(lookback_days):
        d = today - timedelta(days=i)
        f = logs_dir / f"trade_log_{d.strftime('%Y%m%d')}.csv"
        if not f.exists():
            continue
        ok = ma = tw = ai = 0
        for r in _csv.reader(f.open(encoding="utf-8", errors="ignore")):
            if len(r) < 2:
                continue
            res = r[1]
            if res == "OBSERVE_OK":
                ok += 1
            elif "FAST_MA_NEAR" in res:
                ma += 1
            elif res == "OBSERVE_TREND_STRENGTH_WEAK":
                tw += 1
            elif res == "OBSERVE_AI_BLOCK":
                ai += 1
        total = ok + ma + tw + ai
        if total > 0:
            day_stats.append({"date": d.strftime("%Y%m%d"), "ok": ok, "ma": ma, "tw": tw, "ai": ai, "total": total})
            total_ok += ok
            total_ma += ma
            total_tw += tw
            total_ai += ai

    grand_total = total_ok + total_ma + total_tw + total_ai
    ma_pct = round(total_ma / grand_total * 100, 1) if grand_total > 0 else 0.0
    ok_pct = round(total_ok / grand_total * 100, 1) if grand_total > 0 else 0.0

    # Recommend review if MA near blocks dominate (>60% of all blocks) for majority of active days
    ma_dominant_days = sum(1 for d in day_stats if d["total"] > 0 and d["ma"] / d["total"] > 0.60)
    active_days = len(day_stats)
    recommend_review = ma_dominant_days >= max(3, active_days // 2) and ma_pct >= 60.0

    return {
        "lookback_days": lookback_days,
        "active_days": active_days,
        "total_opportunities": grand_total,
        "pass_rate_pct": ok_pct,
        "ma_near_pct": ma_pct,
        "ma_near_count": total_ma,
        "trend_weak_count": total_tw,
        "ai_block_count": total_ai,
        "ma_dominant_days": ma_dominant_days,
        "recommend_review": recommend_review,
        "recommendation": (
            "fast_ma_distance_pct 引き下げ検討 (MA近接が{}日/{}日で支配的 {:.1f}%)".format(
                ma_dominant_days, active_days, ma_pct
            )
            if recommend_review
            else "現状維持 (MA近接={:.1f}%)".format(ma_pct)
        ),
        "day_stats": day_stats[-7:],
    }


def _check_and_update_shadow_inclusion(
    shadow_weekly_review: Dict[str, Any],
    control_path: Path,
    dry_run: bool = False,
    min_closed_n: int = 10,
    promote_wr_pct: float = 44.0,
    promote_pf: float = 1.0,
    exclude_wr_pct: float = 38.0,
    exclude_pf: float = 0.9,
) -> Dict[str, Any]:
    """Auto-manage ai_train_include_shadow based on weekly Shadow performance.

    Promote  → ai_train_include_shadow=1 when WR ≥ promote_wr_pct AND PF ≥ promote_pf
    Exclude  → ai_train_include_shadow=0 when WR < exclude_wr_pct OR PF < exclude_pf
    Hold     → no change (middle ground)
    """
    result: Dict[str, Any] = {
        "action": "skip",
        "reason": "shadow_weekly_review unavailable",
        "before": None,
        "after": None,
    }
    if not isinstance(shadow_weekly_review, dict) or not shadow_weekly_review.get("available"):
        result["reason"] = shadow_weekly_review.get("reason", "shadow_weekly_review unavailable") if isinstance(shadow_weekly_review, dict) else "shadow_weekly_review unavailable"
        return result

    shadow_m = shadow_weekly_review.get("shadow", {})
    wr = float(_safe_float(shadow_m.get("win_rate_pct"), 0.0))
    pf = float(_safe_float(shadow_m.get("profit_factor"), 0.0))
    closed_n = int(_safe_int(shadow_m.get("closed_n"), 0))
    result["shadow_metrics"] = {"closed_n": closed_n, "win_rate_pct": round(wr, 2), "profit_factor": round(pf, 4)}

    if closed_n < min_closed_n:
        result["action"] = "skip"
        result["reason"] = f"insufficient_samples closed_n={closed_n} < min={min_closed_n}"
        return result

    rows = _load_control_rows(control_path)
    current_val = "0"
    for row in rows:
        if row and str(row[0]).strip() == "ai_train_include_shadow":
            current_val = str(row[1]).strip() if len(row) >= 2 else "0"
            break
    result["before"] = current_val

    if wr >= promote_wr_pct and pf >= promote_pf:
        new_val = "1"
        action = "promote"
    elif wr < exclude_wr_pct or pf < exclude_pf:
        new_val = "0"
        action = "exclude"
    else:
        result["action"] = "hold"
        result["reason"] = (
            f"hold WR={wr:.1f}% PF={pf:.4f} closed_n={closed_n} "
            f"(promote≥{promote_wr_pct}%/{promote_pf} exclude<{exclude_wr_pct}%/{exclude_pf})"
        )
        return result

    result["after"] = new_val
    if current_val == new_val:
        result["action"] = "no_change"
        result["reason"] = f"already {new_val} (would={action} WR={wr:.1f}% PF={pf:.4f})"
        return result

    if not dry_run:
        updated_rows, _ = _apply_control_updates_to_rows(rows, {"ai_train_include_shadow": new_val})
        _write_control_rows(control_path, updated_rows)

    result["action"] = action
    result["reason"] = (
        f"WR={wr:.1f}% PF={pf:.4f} closed_n={closed_n} -> ai_train_include_shadow: {current_val} -> {new_val}"
    )
    return result


def _load_json_dict(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(d, dict):
            return d
    except Exception:
        pass
    return {}


def _write_json_dict(path: Path, d: Dict[str, Any]) -> None:
    path.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_weekly_auto_feedback(args: argparse.Namespace) -> int:
    target: Optional[str] = args.target
    start: Optional[str] = args.start
    end: Optional[str] = args.end
    if not target and not start and not end:
        auto_start8, auto_end8 = _resolve_auto_range(args.mode)
        target = f"{auto_start8}-{auto_end8}"
        print(f"[INFO] auto range mode={args.mode} -> {target}")

    wr_args = argparse.Namespace(
        target=target,
        start=start,
        end=end,
        out_dir=args.out_dir,
        logs_dir=args.logs_dir,
        week_start=args.week_start,
        strict=bool(args.strict),
    )
    rc, out_path, report = weekly_report.run_weekly_report(wr_args)
    try:
        shown = out_path.relative_to(ROOT)
    except Exception:
        shown = out_path
    print(f"[OK] weekly report generated: {shown}")

    if rc != 0:
        print(f"[FAIL] weekly_report failed rc={rc}. skip apply/reset.")
        return 1

    ai_feedback = report.get("ai_feedback")
    if not isinstance(ai_feedback, dict):
        print("[WARN] ai_feedback not found in weekly report.")
        ai_feedback = {}
    sug_raw = ai_feedback.get("suggested_control_updates")
    suggested: Dict[str, str] = {}
    if isinstance(sug_raw, dict):
        suggested = {str(k): str(v) for k, v in sug_raw.items()}

    print(f"[INFO] weekly summary: {str(ai_feedback.get('summary', '-'))}")
    if args.print_suggested:
        print(json.dumps(suggested, ensure_ascii=False, indent=2))

    range_obj = report.get("range", {}) if isinstance(report.get("range"), dict) else {}
    range_start8 = str(range_obj.get("start8", "") or "")
    range_end8 = str(range_obj.get("end8", "") or "")
    main_logs_dir = _resolve_path(args.logs_dir) if str(args.logs_dir or "").strip() else (ROOT.parent / "logs")
    main_pattern_summary = _build_weekly_pattern_summary(main_logs_dir, range_start8, range_end8) if range_start8 and range_end8 else {}

    shadow_weekly_review: Dict[str, Any] = {
        "available": False,
        "decision": "評価保留",
        "reason": "shadow logs unavailable",
    }
    shadow_report_path = ""
    shadow_logs_dir = _resolve_path(args.shadow_logs_dir) if str(args.shadow_logs_dir or "").strip() else None
    if shadow_logs_dir is not None:
        if shadow_logs_dir.exists():
            shadow_wr_args = argparse.Namespace(
                target=target,
                start=start,
                end=end,
                out_dir=str(_resolve_path(args.out_dir) / "weekly_shadow_compare"),
                logs_dir=str(shadow_logs_dir),
                week_start=args.week_start,
                strict=bool(args.strict),
            )
            try:
                rc_shadow, out_shadow, shadow_report = weekly_report.run_weekly_report(shadow_wr_args)
                shadow_report_path = str(out_shadow)
                if rc_shadow == 0:
                    shadow_pattern_summary = _build_weekly_pattern_summary(shadow_logs_dir, range_start8, range_end8) if range_start8 and range_end8 else {}
                    shadow_weekly_review = _build_shadow_weekly_review(
                        main_report=report,
                        shadow_report=shadow_report,
                        main_pattern_summary=main_pattern_summary,
                        shadow_pattern_summary=shadow_pattern_summary,
                    )
                    print(
                        "[INFO] weekly shadow review: decision={} reason={}".format(
                            str(shadow_weekly_review.get("decision", "-")),
                            str(shadow_weekly_review.get("reason", "-")),
                        )
                    )
                else:
                    shadow_weekly_review = {
                        "available": False,
                        "decision": "評価保留",
                        "reason": f"shadow weekly report rc={rc_shadow}",
                    }
                    print(f"[WARN] weekly shadow report failed rc={rc_shadow}")
            except Exception as e:
                shadow_weekly_review = {
                    "available": False,
                    "decision": "評価保留",
                    "reason": f"shadow weekly error: {e}",
                }
                print(f"[WARN] weekly shadow review skipped ({e})")
        else:
            shadow_weekly_review = {
                "available": False,
                "decision": "評価保留",
                "reason": f"shadow logs dir missing: {shadow_logs_dir}",
            }
            print(f"[WARN] weekly shadow review skipped (missing {shadow_logs_dir})")

    shadow_sl_cls: Dict[str, Any] = {}
    if shadow_logs_dir is not None and shadow_logs_dir.exists() and range_start8 and range_end8:
        try:
            from tools.shadow_promotion_report import _classify_shadow_sl as _cls_sl
            shadow_sl_cls = _cls_sl(shadow_logs_dir, _get_days_between(range_start8, range_end8))
            print(
                f"[INFO] shadow SL cls: total={shadow_sl_cls.get('sl_n', 0)} "
                f"rw={shadow_sl_cls.get('reversal_wrap_pct', 0.0):.1f}% "
                f"pm={shadow_sl_cls.get('profit_miss_pct', 0.0):.1f}%"
            )
        except Exception as _sl_e:
            print(f"[WARN] shadow SL classification skipped ({_sl_e})")

    control_changed: Dict[str, Dict[str, str]] = {}
    if args.apply_control:
        if not suggested:
            print("[WARN] suggested_control_updates is empty. control update skipped.")
        else:
            control_path = _resolve_path(args.control_path)
            rows = _load_control_rows(control_path)
            updated_rows, control_changed = _apply_control_updates_to_rows(rows, suggested)
            if args.dry_run:
                print(f"[DRYRUN] control update keys={len(control_changed)} path={control_path}")
            else:
                _write_control_rows(control_path, updated_rows)
                print(f"[OK] control updated keys={len(control_changed)} path={control_path}")
            for k in sorted(control_changed.keys()):
                ch = control_changed[k]
                print(f"[UPDATE] {k}: {ch.get('before', '')} -> {ch.get('after', '')}")
    else:
        print("[INFO] control update skipped (--apply-control not set)")

    # --- fast_ma_near filter analysis ---
    fast_ma_analysis = _analyze_fast_ma_filter(
        logs_dir=main_logs_dir if range_start8 else (ROOT.parent / "logs"),
        lookback_days=14,
    )
    print(
        "[INFO] fast_ma_filter: pass_rate={:.1f}% ma_near={:.1f}% recommend_review={} -> {}".format(
            fast_ma_analysis.get("pass_rate_pct", 0),
            fast_ma_analysis.get("ma_near_pct", 0),
            fast_ma_analysis.get("recommend_review", False),
            fast_ma_analysis.get("recommendation", ""),
        )
    )

    # --- Shadow auto re-inclusion check ---
    shadow_inclusion_result = _check_and_update_shadow_inclusion(
        shadow_weekly_review=shadow_weekly_review,
        control_path=_resolve_path(args.control_path),
        dry_run=bool(args.dry_run),
    )
    _action = shadow_inclusion_result.get("action", "skip")
    _reason = shadow_inclusion_result.get("reason", "")
    if _action in ("promote", "exclude"):
        _prefix = "[OK]" if not args.dry_run else "[DRYRUN]"
        print(f"{_prefix} shadow_inclusion {_action}: {_reason}")
    elif _action == "no_change":
        print(f"[INFO] shadow_inclusion no_change: {_reason}")
    elif _action == "hold":
        print(f"[INFO] shadow_inclusion hold: {_reason}")
    else:
        print(f"[INFO] shadow_inclusion skip: {_reason}")

    state_path = _resolve_path(args.state_path)
    state_before = _load_json_dict(state_path)
    drift_status = "UNKNOWN"
    drift_obj = state_before.get("_drift_watch")
    if isinstance(drift_obj, dict):
        drift_status = str(drift_obj.get("status", "UNKNOWN"))

    llm_feedback: Dict[str, Any] = {
        "mode": str(args.llm_mode),
        "provider": "openai" if str(args.llm_mode) == "openai" else "ollama",
        "used": False,
        "summary": "",
        "base_url": _normalize_base_url(args.ollama_base_url),
        "model": str(args.ollama_model),
        "timeout_sec": int(args.ollama_timeout_sec),
        "max_chars": int(args.ollama_max_chars),
        "openai_base_url": normalize_openai_base_url(str(args.openai_base_url)),
        "openai_model": str(args.openai_model),
        "openai_api_key_env": str(args.openai_api_key_env),
        "openai_max_output_tokens": int(args.openai_max_output_tokens),
        "reason": "",
        "error": "",
    }
    if args.llm_mode == "off":
        llm_feedback["reason"] = "llm_mode=off"
        print("[INFO] weekly llm summary skipped (llm_mode=off)")
    else:
        _ai_log_path = main_logs_dir / "ai_training_log.csv"
        _hour_text = _build_ai_log_hour_stats(_ai_log_path, lookback_days=28)
        prompt = _build_weekly_llm_prompt(
            report=report,
            suggested=suggested,
            control_changed=control_changed,
            drift_status=drift_status,
            shadow_weekly_review=shadow_weekly_review,
            ai_log_hour_text=_hour_text,
            shadow_sl_cls=shadow_sl_cls,
        )
        llm_feedback["prompt_chars"] = len(prompt)

        if args.llm_mode == "openai":
            try:
                api_key = os.getenv(str(args.openai_api_key_env), "")
                if not api_key:
                    raise ValueError(f"{args.openai_api_key_env} is empty")
                llm_text = run_openai_responses_summary(
                    api_key=api_key,
                    base_url=str(args.openai_base_url),
                    model=str(args.openai_model),
                    prompt=prompt,
                    instructions=(
                        "日本語で週次トレードレビューを5行に整理する。"
                        "shadowとmainの差分、昇格/保留/差し戻しの根拠、翌週の観察点を明確にする。"
                    ),
                    timeout_sec=int(args.openai_timeout_sec),
                    max_chars=int(args.openai_max_chars),
                    max_output_tokens=int(args.openai_max_output_tokens),
                )
                if _is_low_quality_llm_summary(llm_text):
                    llm_text = _build_fallback_weekly_summary(
                        report=report,
                        suggested=suggested,
                        drift_status=drift_status,
                        shadow_weekly_review=shadow_weekly_review,
                    )
                    llm_feedback["reason"] = "openai_ok_with_fallback"
                else:
                    llm_feedback["reason"] = "openai_ok"
                llm_feedback["used"] = True
                llm_feedback["model"] = str(args.openai_model)
                llm_feedback["base_url"] = normalize_openai_base_url(str(args.openai_base_url))
                llm_feedback["summary"] = llm_text
                llm_feedback["generated_at"] = _now_jst_text()
                llm_feedback["error"] = ""
                print(f"[OK] weekly llm summary generated provider=openai model={args.openai_model} chars={len(llm_text)}")
                for line in llm_text.splitlines():
                    line_s = str(line).strip()
                    if line_s:
                        print(f"[LLM] {line_s}")
            except Exception as e:
                llm_feedback["error"] = str(e)
                llm_feedback["reason"] = "openai_failed"
                print(f"[WARN] weekly llm summary skipped ({llm_feedback['reason']}: {e})")
        else:
            chosen_model = str(args.ollama_model).strip()
            installed_models: List[str] = []
            try:
                installed_models = _ollama_list_models(
                    llm_feedback["base_url"],
                    timeout_sec=int(args.ollama_timeout_sec),
                )
                llm_feedback["installed_models_count"] = len(installed_models)
                if args.llm_mode == "auto":
                    if installed_models:
                        if not any(_is_ollama_model_match(m, chosen_model) for m in installed_models):
                            sorted_models = sorted(installed_models, key=_model_size_score)
                            chosen_model = sorted_models[0]
                            llm_feedback["model"] = chosen_model
                            llm_feedback["reason"] = "requested_model_missing_use_smallest_installed"
                    else:
                        llm_feedback["reason"] = "no_models_installed"
            except Exception as e:
                llm_feedback["error"] = str(e)
                if args.llm_mode == "auto":
                    llm_feedback["reason"] = "tags_fetch_failed"
                else:
                    llm_feedback["reason"] = "tags_fetch_failed_but_try_generate"

            should_run = True
            if args.llm_mode == "auto" and llm_feedback.get("reason") == "no_models_installed":
                should_run = False

            if should_run:
                try:
                    attempt_models: List[str] = [chosen_model]
                    if args.llm_mode == "auto" and installed_models:
                        extra = sorted(
                            [m for m in installed_models if not _is_ollama_model_match(m, chosen_model)],
                            key=_model_size_score,
                        )
                        attempt_models = _unique_keep_order(attempt_models + extra)

                    llm_feedback["attempted_models"] = list(attempt_models)
                    llm_feedback["attempt_errors"] = {}

                    llm_text = ""
                    used_model = chosen_model
                    last_error: Optional[Exception] = None
                    for m in attempt_models:
                        try:
                            llm_text = _run_ollama_weekly_summary(
                                base_url=llm_feedback["base_url"],
                                model=m,
                                prompt=prompt,
                                timeout_sec=int(args.ollama_timeout_sec),
                                max_chars=int(args.ollama_max_chars),
                            )
                            used_model = m
                            break
                        except Exception as e:
                            llm_feedback["attempt_errors"][m] = str(e)
                            last_error = e
                            continue

                    if not llm_text:
                        if last_error is None:
                            raise RuntimeError("ollama generate failed without details")
                        raise last_error

                    if _is_low_quality_llm_summary(llm_text):
                        llm_text = _build_fallback_weekly_summary(
                            report=report,
                            suggested=suggested,
                            drift_status=drift_status,
                            shadow_weekly_review=shadow_weekly_review,
                        )
                        llm_feedback["reason"] = "ok_with_fallback"
                    llm_feedback["used"] = True
                    llm_feedback["model"] = used_model
                    llm_feedback["summary"] = llm_text
                    llm_feedback["generated_at"] = _now_jst_text()
                    if llm_feedback.get("reason") in ("", "tags_fetch_failed", "tags_fetch_failed_but_try_generate", "generate_failed"):
                        llm_feedback["reason"] = "ok"
                    llm_feedback["error"] = ""
                    print(f"[OK] weekly llm summary generated model={used_model} chars={len(llm_text)}")
                    for line in llm_text.splitlines():
                        line_s = str(line).strip()
                        if line_s:
                            print(f"[LLM] {line_s}")
                except Exception as e:
                    llm_feedback["error"] = str(e)
                    if not llm_feedback.get("reason"):
                        llm_feedback["reason"] = "generate_failed"
                    print(f"[WARN] weekly llm summary skipped ({llm_feedback['reason']}: {e})")
            else:
                print(f"[WARN] weekly llm summary skipped ({llm_feedback['reason']})")

    if args.reset_auto_train_day:
        st = dict(state_before)
        before_day = str(st.get("_ai_auto_train_day", ""))
        st["_ai_auto_train_day"] = ""
        st["_weekly_auto_feedback"] = {
            "updated_at": _now_jst_text(),
            "report_path": str(out_path),
            "shadow_report_path": shadow_report_path,
            "range_start8": str(report.get("range", {}).get("start8", "")),
            "range_end8": str(report.get("range", {}).get("end8", "")),
            "summary": str(ai_feedback.get("summary", "")),
            "apply_control": bool(args.apply_control),
            "control_changed_keys": sorted(control_changed.keys()),
            "suggested_control_updates": suggested,
            "main_weekly_pattern_summary": main_pattern_summary,
            "shadow_weekly_review": shadow_weekly_review,
            "shadow_sl_cls": shadow_sl_cls,
            "shadow_inclusion": shadow_inclusion_result,
            "fast_ma_filter_analysis": fast_ma_analysis,
            "llm_feedback": llm_feedback,
        }
        if args.dry_run:
            print(f"[DRYRUN] state update path={state_path} _ai_auto_train_day: {before_day} -> ''")
        else:
            _write_json_dict(state_path, st)
            print(f"[OK] state updated path={state_path} _ai_auto_train_day: {before_day} -> ''")
    else:
        print("[INFO] state reset skipped (--reset-auto-train-day not set)")

    # TP/SL sweep: notify if a better combo is found (non-blocking, safe to fail)
    try:
        _run_sweep_and_notify(
            control_path=_resolve_path(args.control_path),
            secrets_path=ROOT / ".streamlit" / "secrets.toml",
            dry_run=bool(args.dry_run),
        )
    except Exception as _sweep_exc:
        print(f"[sweep] unexpected error: {_sweep_exc}")

    # PDCA自動追記: pdca_daily_update.py に委譲（--no-notify で重複通知回避）
    try:
        import subprocess as _subproc
        pdca_cmd = [
            sys.executable,
            str(ROOT / "tools" / "pdca_daily_update.py"),
        ]
        if args.dry_run:
            pdca_cmd.append("--dry-run")
        pdca_cmd.append("--no-notify")
        _pdca_proc = _subproc.run(
            pdca_cmd, capture_output=True, text=True, timeout=45.0, cwd=str(ROOT)
        )
        print(_pdca_proc.stdout.strip())
        if _pdca_proc.returncode != 0:
            print(f"[WARN] pdca_daily_update rc={_pdca_proc.returncode}: {_pdca_proc.stderr.strip()[:200]}")
    except Exception as _pdca_exc:
        print(f"[WARN] pdca_daily_update failed: {_pdca_exc}")

    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=(
            "Generate weekly_report, optionally apply ai_feedback suggested control updates, "
            "and optionally reset _ai_auto_train_day for next bot auto-train cycle."
        )
    )
    ap.add_argument("target", nargs="?", default=None, help="day8 (YYYYMMDD) or range (YYYYMMDD-YYYYMMDD)")
    ap.add_argument("--start", default=None, help="range start day8 (YYYYMMDD)")
    ap.add_argument("--end", default=None, help="range end day8 (YYYYMMDD)")
    ap.add_argument(
        "--mode",
        choices=("previous-week", "last7"),
        default="previous-week",
        help="auto range mode when target/start/end are not set (default: previous-week)",
    )
    ap.add_argument("--week-start", choices=WEEKDAY_CHOICES, default="MON")
    ap.add_argument("--out-dir", default="weekly_report_out")
    ap.add_argument("--logs-dir", default=None)
    ap.add_argument("--shadow-logs-dir", default="../logs/instances/shadow", help="shadow logs dir for weekly compare")
    ap.add_argument("--strict", action="store_true", help="pass --strict to weekly_report")

    ap.add_argument("--apply-control", action="store_true", help="apply ai_feedback.suggested_control_updates to CONTROL.csv")
    ap.add_argument("--control-path", default="CONTROL.csv", help="control csv path (default: CONTROL.csv)")
    ap.add_argument(
        "--reset-auto-train-day",
        action="store_true",
        help="set state._ai_auto_train_day='' so bot can run auto-train again on next tick",
    )
    ap.add_argument("--state-path", default="state.json", help="state json path (default: state.json)")
    ap.add_argument(
        "--llm-mode",
        choices=("off", "auto", "ollama", "openai"),
        default="auto",
        help="weekly summary comment mode (default: auto)",
    )
    ap.add_argument(
        "--ollama-base-url",
        default=OLLAMA_BASE_URL_DEFAULT,
        help=f"ollama endpoint base URL (default: {OLLAMA_BASE_URL_DEFAULT})",
    )
    ap.add_argument(
        "--ollama-model",
        default=OLLAMA_MODEL_DEFAULT,
        help=f"ollama model name (default: {OLLAMA_MODEL_DEFAULT})",
    )
    ap.add_argument(
        "--ollama-timeout-sec",
        type=int,
        default=OLLAMA_TIMEOUT_SEC_DEFAULT,
        help=f"ollama request timeout seconds (default: {OLLAMA_TIMEOUT_SEC_DEFAULT})",
    )
    ap.add_argument(
        "--ollama-max-chars",
        type=int,
        default=OLLAMA_MAX_CHARS_DEFAULT,
        help=f"max chars for saved/printed llm summary (default: {OLLAMA_MAX_CHARS_DEFAULT})",
    )
    ap.add_argument(
        "--openai-base-url",
        default=OPENAI_BASE_URL_DEFAULT,
        help=f"OpenAI API base URL for --llm-mode openai (default: {OPENAI_BASE_URL_DEFAULT})",
    )
    ap.add_argument(
        "--openai-model",
        default=OPENAI_MODEL_DEFAULT,
        help=f"OpenAI model for --llm-mode openai (default: {OPENAI_MODEL_DEFAULT})",
    )
    ap.add_argument(
        "--openai-api-key-env",
        default=OPENAI_API_KEY_ENV_DEFAULT,
        help=f"env var name that stores the OpenAI API key (default: {OPENAI_API_KEY_ENV_DEFAULT})",
    )
    ap.add_argument(
        "--openai-timeout-sec",
        type=int,
        default=120,
        help="OpenAI request timeout seconds for --llm-mode openai (default: 120)",
    )
    ap.add_argument(
        "--openai-max-chars",
        type=int,
        default=OLLAMA_MAX_CHARS_DEFAULT,
        help=f"max chars for saved/printed OpenAI weekly summary (default: {OLLAMA_MAX_CHARS_DEFAULT})",
    )
    ap.add_argument(
        "--openai-max-output-tokens",
        type=int,
        default=OPENAI_MAX_OUTPUT_TOKENS_DEFAULT,
        help=f"OpenAI max_output_tokens for --llm-mode openai (default: {OPENAI_MAX_OUTPUT_TOKENS_DEFAULT})",
    )
    ap.add_argument("--print-suggested", action="store_true", help="print suggested_control_updates JSON")
    ap.add_argument("--dry-run", action="store_true", help="do not write CONTROL/state")
    return ap


def main() -> None:
    ap = build_arg_parser()
    args = ap.parse_args()
    try:
        rc = run_weekly_auto_feedback(args)
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
