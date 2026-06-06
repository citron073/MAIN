#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import bot
from tools.trade_event_notifier import _build_daily_trade_review, _technical_feature_labels_from_note


DEFAULT_LOGS_DIR = ROOT_DIR.parent / "logs"
DEFAULT_SHADOW_LOGS_DIR = DEFAULT_LOGS_DIR / "instances" / "shadow"
DEFAULT_REPORT_OUT_DIR = ROOT_DIR / "daily_report_out"
DEFAULT_CONTROL_PATH = ROOT_DIR / "CONTROL.csv"
DEFAULT_AI_MODEL_PATH = ROOT_DIR / "ai_model.json"
DEFAULT_OUT_DIR = ROOT_DIR / "review_out"


FEATURE_PREFIXES = (
    "aiba_",
    "phase",
    "pattern",
    "gc_recent",
    "gc_strong",
    "rsi",
    "bb",
    "atr",
    "trend_power",
    "up_break",
    "down_break",
)


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(float(v))
    except Exception:
        return int(default)


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _read_control_csv(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    out: Dict[str, str] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = str(row.get("key", "") or "").strip()
            if key:
                out[key] = str(row.get("value", "") or "").strip()
    return out


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _log_days(logs_dir: Path) -> List[str]:
    if not logs_dir.exists():
        return []
    days: List[str] = []
    for path in logs_dir.glob("trade_log_*.csv"):
        m = re.match(r"^trade_log_(\d{8})\.csv$", path.name)
        if m:
            days.append(m.group(1))
    return sorted(set(days))


def resolve_days(
    *,
    main_logs_dir: Path,
    shadow_logs_dir: Path,
    days: Optional[List[str]] = None,
    lookback_days: int = 90,
) -> List[str]:
    if days:
        return sorted({str(x).strip() for x in days if str(x).strip()})
    all_days = sorted(set(_log_days(main_logs_dir)) | set(_log_days(shadow_logs_dir)))
    if int(lookback_days) <= 0:
        return all_days
    return all_days[-int(lookback_days):]


def resolve_paths_from_snapshot(snapshot_dir: Path) -> Dict[str, Path]:
    base = Path(snapshot_dir).expanduser()
    return {
        "main_logs_dir": base / "logs",
        "shadow_logs_dir": base / "logs" / "instances" / "shadow",
        "report_out_dir": base / "MAIN" / "daily_report_out",
        "control_path": base / "MAIN" / "CONTROL.csv",
        "ai_model_path": base / "MAIN" / "ai_model.json",
    }


def _empty_summary() -> Dict[str, Any]:
    return {
        "active_days": 0,
        "closed_n": 0,
        "win_n": 0,
        "loss_n": 0,
        "flat_n": 0,
        "win_rate_pct": 0.0,
        "pnl_jpy_sum": 0.0,
        "ret_sum_pct": 0.0,
        "avg_ret_pct": 0.0,
        "mfe_sum_pct": 0.0,
        "mae_proxy_sum_pct": 0.0,
        "giveback_sum_pct": 0.0,
        "avg_mfe_pct": 0.0,
        "avg_mae_proxy_pct": 0.0,
        "avg_giveback_pct": 0.0,
        "progress_reached_n": 0,
        "gross_profit_jpy": 0.0,
        "gross_loss_jpy": 0.0,
        "profit_factor_jpy": 0.0,
        "tp_n": 0,
        "sl_n": 0,
        "timeout_n": 0,
        "pre_news_n": 0,
        "eod_n": 0,
        "sl_rate_pct": 0.0,
        "timeout_rate_pct": 0.0,
        "skip_news_n": 0,
        "skip_spread_n": 0,
        "observe_ai_block_n": 0,
        "observe_phase_b_n": 0,
        "near_tp_giveback_exit_n": 0,
        "no_follow_through_exit_n": 0,
        "progress_reversal_exit_n": 0,
        "progress_timeout_n": 0,
        "weak_progress_exit_n": 0,
    }


def _merge_counter_row(dst: Dict[str, Any], src: Dict[str, Any]) -> None:
    for key in ("n", "win_n", "loss_n", "flat_n", "TP", "SL", "TIMEOUT", "OTHER"):
        dst[key] = int(_safe_int(dst.get(key), 0)) + int(_safe_int(src.get(key), 0))
    for key in ("ret_sum_pct", "pnl_jpy_sum", "mfe_sum_pct", "mae_proxy_sum_pct", "giveback_sum_pct"):
        dst[key] = float(_safe_float(dst.get(key), 0.0)) + float(_safe_float(src.get(key), 0.0))
    for key in ("mfe_n", "mae_proxy_n", "giveback_n"):
        dst[key] = int(_safe_int(dst.get(key), 0)) + int(_safe_int(src.get(key), 0))


def _finalize_feature_table(table: Dict[str, Dict[str, Any]], *, limit: int = 20) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for label, raw in table.items():
        n = int(_safe_int(raw.get("n"), 0))
        if n <= 0:
            continue
        win_n = int(_safe_int(raw.get("win_n"), 0))
        pnl = float(_safe_float(raw.get("pnl_jpy_sum"), 0.0))
        ret_sum = float(_safe_float(raw.get("ret_sum_pct"), 0.0))
        rows.append(
            {
                "label": str(label),
                "n": n,
                "win_n": win_n,
                "loss_n": int(_safe_int(raw.get("loss_n"), 0)),
                "win_rate_pct": round(float(win_n) / float(n) * 100.0, 4),
                "pnl_jpy_sum": round(pnl, 6),
                "ret_sum_pct": round(ret_sum, 6),
                "avg_ret_pct": round(ret_sum / float(n), 6),
                "avg_mfe_pct": round(float(_safe_float(raw.get("mfe_sum_pct"), 0.0)) / float(max(1, _safe_int(raw.get("mfe_n"), 0))), 6)
                if _safe_int(raw.get("mfe_n"), 0) > 0
                else 0.0,
                "avg_mae_proxy_pct": round(
                    float(_safe_float(raw.get("mae_proxy_sum_pct"), 0.0)) / float(max(1, _safe_int(raw.get("mae_proxy_n"), 0))),
                    6,
                )
                if _safe_int(raw.get("mae_proxy_n"), 0) > 0
                else 0.0,
                "avg_giveback_pct": round(
                    float(_safe_float(raw.get("giveback_sum_pct"), 0.0)) / float(max(1, _safe_int(raw.get("giveback_n"), 0))),
                    6,
                )
                if _safe_int(raw.get("giveback_n"), 0) > 0
                else 0.0,
                "TP": int(_safe_int(raw.get("TP"), 0)),
                "SL": int(_safe_int(raw.get("SL"), 0)),
                "TIMEOUT": int(_safe_int(raw.get("TIMEOUT"), 0)),
            }
        )
    rows.sort(key=lambda r: (-abs(float(r["pnl_jpy_sum"])), -int(r["n"]), str(r["label"])))
    return rows[: int(limit)]


def _feature_rows_by_prefix(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for prefix in FEATURE_PREFIXES:
        out[prefix] = [row for row in rows if str(row.get("label", "")).startswith(prefix)][:8]
    return {k: v for k, v in out.items() if v}


def collect_feature_presence(logs_dir: Path, days: List[str], *, limit: int = 20) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = defaultdict(int)
    for day8 in days:
        path = logs_dir / f"trade_log_{day8}.csv"
        if not path.exists():
            continue
        try:
            with path.open(newline="", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    for label in _technical_feature_labels_from_note(row.get("note", "")):
                        counts[str(label)] += 1
        except Exception:
            continue
    rows = [{"label": label, "count": count} for label, count in counts.items() if int(count) > 0]
    rows.sort(key=lambda r: (-int(r["count"]), str(r["label"])))
    return rows[: int(limit)]


def aggregate_reviews(reviews: Iterable[Dict[str, Any]], *, feature_limit: int = 20) -> Dict[str, Any]:
    out = _empty_summary()
    feature_table: Dict[str, Dict[str, Any]] = defaultdict(dict)
    phase_table: Dict[str, Dict[str, Any]] = defaultdict(dict)
    for review in reviews:
        if int(_safe_int(review.get("active_row_n"), 0)) > 0 or int(_safe_int(review.get("closed_n"), 0)) > 0:
            out["active_days"] += 1
        for key in (
            "closed_n",
            "win_n",
            "loss_n",
            "flat_n",
            "skip_news_n",
            "skip_spread_n",
            "observe_ai_block_n",
            "observe_phase_b_n",
            "near_tp_giveback_exit_n",
            "no_follow_through_exit_n",
            "progress_reversal_exit_n",
            "progress_timeout_n",
            "weak_progress_exit_n",
            "progress_reached_n",
        ):
            out[key] += int(_safe_int(review.get(key), 0))
        for key in ("pnl_jpy_sum", "ret_sum_pct", "mfe_sum_pct", "mae_proxy_sum_pct", "giveback_sum_pct", "gross_profit_jpy", "gross_loss_jpy"):
            out[key] += float(_safe_float(review.get(key), 0.0))
        br = review.get("exit_reason_breakdown") if isinstance(review.get("exit_reason_breakdown"), dict) else {}
        out["tp_n"] += int(_safe_int(br.get("TP"), 0))
        out["sl_n"] += int(_safe_int(br.get("SL"), 0))
        out["timeout_n"] += int(_safe_int(br.get("TIMEOUT"), 0))
        out["pre_news_n"] += int(_safe_int(br.get("PRENEWS"), 0))
        out["eod_n"] += int(_safe_int(br.get("EOD"), 0))

        tf = review.get("technical_feature_outcomes")
        if isinstance(tf, dict):
            for label, row in tf.items():
                if isinstance(row, dict):
                    _merge_counter_row(feature_table[str(label)], row)
        ph = review.get("market_phase_outcomes")
        if isinstance(ph, dict):
            for label, row in ph.items():
                if isinstance(row, dict):
                    _merge_counter_row(phase_table[str(label)], row)

    closed = int(out["closed_n"])
    if closed > 0:
        out["win_rate_pct"] = round(float(out["win_n"]) / float(closed) * 100.0, 4)
        out["avg_ret_pct"] = round(float(out["ret_sum_pct"]) / float(closed), 6)
        out["avg_mfe_pct"] = round(float(out["mfe_sum_pct"]) / float(closed), 6)
        out["avg_mae_proxy_pct"] = round(float(out["mae_proxy_sum_pct"]) / float(closed), 6)
        out["avg_giveback_pct"] = round(float(out["giveback_sum_pct"]) / float(closed), 6)
        out["sl_rate_pct"] = round(float(out["sl_n"]) / float(closed) * 100.0, 4)
        out["timeout_rate_pct"] = round(float(out["timeout_n"]) / float(closed) * 100.0, 4)
    abs_loss = abs(float(out["gross_loss_jpy"]))
    out["profit_factor_jpy"] = round(
        (float(out["gross_profit_jpy"]) / abs_loss) if abs_loss > 0 else (8.0 if float(out["gross_profit_jpy"]) > 0 else 0.0),
        6,
    )
    for key in ("pnl_jpy_sum", "ret_sum_pct", "mfe_sum_pct", "mae_proxy_sum_pct", "giveback_sum_pct", "gross_profit_jpy", "gross_loss_jpy"):
        out[key] = round(float(out[key]), 6)
    out["feature_outcomes_top"] = _finalize_feature_table(feature_table, limit=feature_limit)
    out["feature_outcomes_by_prefix"] = _feature_rows_by_prefix(out["feature_outcomes_top"])
    out["market_phase_outcomes"] = {row["label"]: row for row in _finalize_feature_table(phase_table, limit=10)}
    return out


def _effective_config(control_path: Path, ai_model_path: Path) -> Dict[str, Any]:
    control = _read_control_csv(control_path)
    ai_model = bot.read_ai_model_json(ai_model_path) if ai_model_path.exists() else {}
    cfg = bot.build_runtime_config(control, ai_model)
    keys = [
        "trade_enabled",
        "today_on",
        "paper_mode",
        "observe_only",
        "live_enabled",
        "rollout_mode",
        "daily_loss_limit_pct",
        "ai_enabled",
        "ai_mode",
        "ai_th_entry",
        "ai_use_chart_patterns",
        "ai_use_market_phase",
        "ai_use_aiba_style",
        "chart_pattern_enabled",
        "market_phase_enabled",
        "market_phase_block_b_enabled",
        "aiba_style_enabled",
        "aiba_style_ai_enabled",
        "near_tp_giveback_exit_enabled",
        "no_follow_through_exit_enabled",
        "progress_reversal_exit_enabled",
        "weak_progress_exit_enabled",
    ]
    return {
        "control_path": str(control_path),
        "ai_model_path": str(ai_model_path),
        "bot_version": bot.OUROBOROS_BOT_VERSION,
        "feature_schema": bot.OUROBOROS_FEATURE_SCHEMA_VERSION,
        "values": {key: getattr(cfg, key) for key in keys if hasattr(cfg, key)},
        "raw_control_high_risk": {
            key: control.get(key, "")
            for key in (
                "trade_enabled",
                "paper_mode",
                "live_enabled",
                "safety_hard_block",
                "daily_loss_limit_pct",
                "lot",
                "product_code",
                "market_type",
            )
            if key in control
        },
    }


def _missing_info(
    *,
    main_logs_dir: Path,
    shadow_logs_dir: Path,
    report_out_dir: Path,
    compare_targets: Optional[List[str]],
    snapshot_dir: Optional[Path] = None,
) -> List[str]:
    missing: List[str] = []
    if snapshot_dir is not None and not snapshot_dir.exists():
        missing.append(f"VM snapshot directory: 未指定または存在しない ({snapshot_dir})")
    if not _log_days(main_logs_dir):
        missing.append("直近3ヶ月の実践トレード結果: 未指定またはmain trade_logなし")
    if not _log_days(shadow_logs_dir):
        missing.append("直近3ヶ月のサンプルトレード結果: 未指定またはshadow trade_logなし")
    if not compare_targets:
        missing.append("比較対象システムA/B/C: 未指定")
    if not report_out_dir.exists() or not list(report_out_dir.glob("daily_reflection_*.json")):
        missing.append("日次反省レポート: 未指定またはdaily_reflectionなし")
    return missing


def _risk_flags(main: Dict[str, Any], shadow: Dict[str, Any], config: Dict[str, Any]) -> List[str]:
    flags: List[str] = []
    vals = config.get("values") if isinstance(config.get("values"), dict) else {}
    if str(vals.get("trade_enabled")).lower() in ("false", "0"):
        flags.append("main trade_enabled is false; 再開判断は別途必要")
    if bool(vals.get("live_enabled")) and not bool(vals.get("paper_mode")):
        flags.append("LIVE mode is enabled; main変更はshadow/observe通過後だけ")
    if float(_safe_float(shadow.get("pnl_jpy_sum"), 0.0)) < 0 and int(_safe_int(shadow.get("closed_n"), 0)) >= 10:
        flags.append("shadow aggregate is negative with enough samples; main昇格禁止候補")
    if float(_safe_float(main.get("sl_rate_pct"), 0.0)) > 40.0:
        flags.append("main SL rate is high; entry filter or early exit review needed")
    if int(_safe_int(main.get("closed_n"), 0)) < 10:
        flags.append("main closed samples are thin; avoid parameter changes based only on this window")
    return flags


def _hypotheses(main: Dict[str, Any], shadow: Dict[str, Any]) -> List[Dict[str, str]]:
    return [
        {
            "hypothesis": "レジーム変化に追従できず、B局面または逆方向局面で期待値が落ちている",
            "validation": "market_phase_outcomes の A/B/C別 pnl, win, SL/TIMEOUT を比較する",
        },
        {
            "hypothesis": "TP寸前から戻される玉を利確できず、TIMEOUT/SLへ悪化している",
            "validation": "best_fav と near_tp_giveback_exit_n、progress_timeout_n の推移を見る",
        },
        {
            "hypothesis": "Aiba/PPP/くちばし系シグナルが方向選別に効いていない、または過剰反応している",
            "validation": "feature_outcomes_by_prefix.aiba_ の avg_ret_pct と n を3営業日以上で評価する",
        },
        {
            "hypothesis": "shadow改善がmainより悪く、昇格候補が逆効果になっている",
            "validation": "同一日・同一時間帯で main と shadow の pnl_jpy_sum / avg_ret_pct を比較する",
        },
        {
            "hypothesis": "実効設定が想定と違い、AI/phase/aibaの反映ON/OFFを誤認している",
            "validation": "effective_config.values を朝チェックに出し、CONTROLとai_modelの上書きを確認する",
        },
        {
            "hypothesis": "時間帯・ニュース・スプレッドで機会損失または悪い約定が偏っている",
            "validation": "hour別・skip_news/skip_spread/observe_time_block別の勝率とpnlを比較する",
        },
    ]


def build_review(
    *,
    main_logs_dir: Path = DEFAULT_LOGS_DIR,
    shadow_logs_dir: Path = DEFAULT_SHADOW_LOGS_DIR,
    report_out_dir: Path = DEFAULT_REPORT_OUT_DIR,
    control_path: Path = DEFAULT_CONTROL_PATH,
    ai_model_path: Path = DEFAULT_AI_MODEL_PATH,
    days: Optional[List[str]] = None,
    lookback_days: int = 90,
    compare_targets: Optional[List[str]] = None,
    snapshot_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    resolved_snapshot_dir: Optional[Path] = None
    if snapshot_dir is not None and str(snapshot_dir).strip():
        resolved_snapshot_dir = Path(snapshot_dir).expanduser()
        paths = resolve_paths_from_snapshot(resolved_snapshot_dir)
        main_logs_dir = paths["main_logs_dir"]
        shadow_logs_dir = paths["shadow_logs_dir"]
        report_out_dir = paths["report_out_dir"]
        control_path = paths["control_path"]
        ai_model_path = paths["ai_model_path"]

    resolved_days = resolve_days(
        main_logs_dir=main_logs_dir,
        shadow_logs_dir=shadow_logs_dir,
        days=days,
        lookback_days=lookback_days,
    )
    main_reviews = [_build_daily_trade_review(main_logs_dir, day8) for day8 in resolved_days]
    shadow_reviews = [_build_daily_trade_review(shadow_logs_dir, day8) for day8 in resolved_days]
    main = aggregate_reviews(main_reviews)
    shadow = aggregate_reviews(shadow_reviews)
    main["feature_presence_top"] = collect_feature_presence(main_logs_dir, resolved_days)
    shadow["feature_presence_top"] = collect_feature_presence(shadow_logs_dir, resolved_days)
    config = _effective_config(control_path, ai_model_path)
    return {
        "generated_at": _now_text(),
        "scope": {
            "root": str(ROOT_DIR),
            "source_mode": "vm_snapshot" if resolved_snapshot_dir is not None else "local",
            "snapshot_dir": str(resolved_snapshot_dir) if resolved_snapshot_dir is not None else "",
            "days": resolved_days,
            "lookback_days": int(lookback_days),
            "main_logs_dir": str(main_logs_dir),
            "shadow_logs_dir": str(shadow_logs_dir),
            "report_out_dir": str(report_out_dir),
        },
        "safety": {
            "local_only": True,
            "writes_control": False,
            "service_restarts": False,
            "external_api": False,
            "secrets_read": False,
            "auto_commit": False,
        },
        "missing_info": _missing_info(
            main_logs_dir=main_logs_dir,
            shadow_logs_dir=shadow_logs_dir,
            report_out_dir=report_out_dir,
            compare_targets=compare_targets,
            snapshot_dir=resolved_snapshot_dir,
        ),
        "effective_config": config,
        "main": main,
        "shadow": shadow,
        "risk_flags": _risk_flags(main, shadow, config),
        "hypotheses": _hypotheses(main, shadow),
        "comparison": {
            "targets": compare_targets or [],
            "status": "not_computed" if not compare_targets else "axis_only",
            "reason": "比較対象システムA/B/Cが未指定" if not compare_targets else "比較対象のログパス定義が未指定",
            "axes": [
                "期間",
                "closed_n",
                "pnl_jpy_sum",
                "win_rate_pct",
                "profit_factor_jpy",
                "sl_rate_pct",
                "timeout_rate_pct",
                "feature_outcomes",
                "service/log completeness",
            ],
        },
    }


def format_markdown(review: Dict[str, Any]) -> str:
    main = review.get("main", {})
    shadow = review.get("shadow", {})
    cfg = review.get("effective_config", {}).get("values", {})
    lines = [
        "# Trade System Review",
        "",
        f"- generated_at: {review.get('generated_at')}",
        f"- source_mode: {review.get('scope', {}).get('source_mode', 'local')}",
        f"- snapshot_dir: {review.get('scope', {}).get('snapshot_dir', '') or '-'}",
        f"- days: {', '.join(review.get('scope', {}).get('days', [])) or '-'}",
        f"- bot_version: {review.get('effective_config', {}).get('bot_version', '-')}",
        f"- feature_schema: {review.get('effective_config', {}).get('feature_schema', '-')}",
        "",
        "## Safety",
        "- local_only: true",
        "- writes_control: false",
        "- service_restarts: false",
        "- external_api: false",
        "",
        "## Effective Config",
    ]
    for key in sorted(cfg):
        lines.append(f"- {key}: {cfg[key]}")
    lines.extend(
        [
            "",
            "## Main Summary",
            f"- closed={main.get('closed_n', 0)} win={main.get('win_rate_pct', 0)}% pnl={float(_safe_float(main.get('pnl_jpy_sum'), 0.0)):+.0f} PF={main.get('profit_factor_jpy', 0)} SL={main.get('sl_rate_pct', 0)}% TIMEOUT={main.get('timeout_rate_pct', 0)}%",
            f"- avg_mfe={main.get('avg_mfe_pct', 0)}% avg_mae_proxy={main.get('avg_mae_proxy_pct', 0)}% avg_giveback={main.get('avg_giveback_pct', 0)}% progress_reached={main.get('progress_reached_n', 0)}",
            "",
            "## Shadow Summary",
            f"- closed={shadow.get('closed_n', 0)} win={shadow.get('win_rate_pct', 0)}% pnl={float(_safe_float(shadow.get('pnl_jpy_sum'), 0.0)):+.0f} PF={shadow.get('profit_factor_jpy', 0)} SL={shadow.get('sl_rate_pct', 0)}% TIMEOUT={shadow.get('timeout_rate_pct', 0)}%",
            f"- avg_mfe={shadow.get('avg_mfe_pct', 0)}% avg_mae_proxy={shadow.get('avg_mae_proxy_pct', 0)}% avg_giveback={shadow.get('avg_giveback_pct', 0)}% progress_reached={shadow.get('progress_reached_n', 0)}",
            "",
            "## Risk Flags",
        ]
    )
    flags = review.get("risk_flags") or []
    lines.extend([f"- {x}" for x in flags] if flags else ["- none"])
    lines.extend(["", "## Missing Info"])
    missing = review.get("missing_info") or []
    lines.extend([f"- {x}" for x in missing] if missing else ["- none"])
    lines.extend(["", "## Feature Outcomes Top"])
    rows = main.get("feature_outcomes_top") or []
    if rows:
        lines.append("| label | n | win | pnl | avg_ret | mfe/mae/giveback | TP/SL/TO |")
        lines.append("|---|---:|---:|---:|---:|---:|---|")
        for row in rows[:12]:
            lines.append(
                f"| {row.get('label')} | {row.get('n')} | {row.get('win_rate_pct')}% | "
                f"{float(_safe_float(row.get('pnl_jpy_sum'), 0.0)):+.0f} | {row.get('avg_ret_pct')} | "
                f"{row.get('avg_mfe_pct', 0)}/{row.get('avg_mae_proxy_pct', 0)}/{row.get('avg_giveback_pct', 0)} | "
                f"{row.get('TP')}/{row.get('SL')}/{row.get('TIMEOUT')} |"
            )
    else:
        lines.append("- none")
    lines.extend(["", "## Feature Presence Top"])
    presence = main.get("feature_presence_top") or []
    if presence:
        lines.append("| label | count |")
        lines.append("|---|---:|")
        for row in presence[:12]:
            lines.append(f"| {row.get('label')} | {row.get('count')} |")
    else:
        lines.append("- none")
    lines.extend(["", "## Hypotheses"])
    for item in review.get("hypotheses") or []:
        lines.append(f"- {item.get('hypothesis')} / verify: {item.get('validation')}")
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Local-only Ouroboros trade system review.")
    p.add_argument("--snapshot-dir", default="", help="Use read-only VM snapshot directory produced by sync_vm_llm_inputs.sh.")
    p.add_argument("--main-logs-dir", default=str(DEFAULT_LOGS_DIR))
    p.add_argument("--shadow-logs-dir", default=str(DEFAULT_SHADOW_LOGS_DIR))
    p.add_argument("--report-out-dir", default=str(DEFAULT_REPORT_OUT_DIR))
    p.add_argument("--control-path", default=str(DEFAULT_CONTROL_PATH))
    p.add_argument("--ai-model-path", default=str(DEFAULT_AI_MODEL_PATH))
    p.add_argument("--lookback-days", type=int, default=90)
    p.add_argument("--day", action="append", dest="days", help="Specific YYYYMMDD day. Can be passed multiple times.")
    p.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    p.add_argument("--print-json", action="store_true")
    p.add_argument("--write", action="store_true", help="Write JSON and markdown under review_out.")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    review = build_review(
        main_logs_dir=Path(args.main_logs_dir),
        shadow_logs_dir=Path(args.shadow_logs_dir),
        report_out_dir=Path(args.report_out_dir),
        control_path=Path(args.control_path),
        ai_model_path=Path(args.ai_model_path),
        days=args.days,
        lookback_days=int(args.lookback_days),
        snapshot_dir=Path(args.snapshot_dir) if str(args.snapshot_dir or "").strip() else None,
    )
    if args.write:
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = out_dir / f"trade_system_review_{stamp}.json"
        md_path = out_dir / f"trade_system_review_{stamp}.md"
        json_path.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        md_path.write_text(format_markdown(review), encoding="utf-8")
        print(f"[OK] wrote {json_path}")
        print(f"[OK] wrote {md_path}")
    elif args.print_json:
        print(json.dumps(review, ensure_ascii=False, indent=2))
    else:
        print(format_markdown(review))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
