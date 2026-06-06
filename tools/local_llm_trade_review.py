#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools import mr_observe_summary, shadow_promotion_report, time_block_review
from tools.llm_provider import list_ollama_models, normalize_ollama_base_url, run_ollama_generate_summary
from tools.trade_event_notifier import _build_daily_trade_review


DEFAULT_LOGS_DIR = ROOT_DIR.parent / "logs"
DEFAULT_SHADOW_LOGS_DIR = DEFAULT_LOGS_DIR / "instances" / "shadow"
DEFAULT_MR_LOGS_DIR = DEFAULT_LOGS_DIR / "instances" / "mr_observe"
DEFAULT_REFLECTION_DIR = ROOT_DIR / "daily_report_out"
DEFAULT_CONTROL_PATH = ROOT_DIR / "CONTROL.csv"
DEFAULT_OUT_DIR = ROOT_DIR / ".local_llm" / "reports"
DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "qwen2.5:1.5b"


def _now_jst_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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


def _read_control(path: Path) -> Dict[str, str]:
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
        m = re.match(r"trade_log_(\d{8})\.csv$", path.name)
        if m:
            days.append(m.group(1))
    return sorted(set(days))


def resolve_day8(main_logs_dir: Path, shadow_logs_dir: Path, mr_logs_dir: Path, day8: str = "") -> str:
    chosen = str(day8 or "").strip()
    if chosen:
        return chosen
    days = sorted(set(_log_days(main_logs_dir)) | set(_log_days(shadow_logs_dir)) | set(_log_days(mr_logs_dir)))
    return days[-1] if days else datetime.now().strftime("%Y%m%d")


def resolve_paths_from_snapshot(snapshot_dir: Path) -> Dict[str, Path]:
    base = Path(snapshot_dir).expanduser()
    return {
        "logs_dir": base / "logs",
        "shadow_logs_dir": base / "logs" / "instances" / "shadow",
        "mr_logs_dir": base / "logs" / "instances" / "mr_observe",
        "reflection_dir": base / "MAIN" / "daily_report_out",
        "control_path": base / "MAIN" / "CONTROL.csv",
    }


def _load_reflection(reflection_dir: Path, day8: str) -> Dict[str, Any]:
    exact = reflection_dir / f"daily_reflection_{day8}.json"
    if exact.exists():
        return _read_json(exact)
    files = sorted(reflection_dir.glob("daily_reflection_*.json")) if reflection_dir.exists() else []
    return _read_json(files[-1]) if files else {}


def _control_subset(control: Dict[str, str]) -> Dict[str, str]:
    keys = [
        "trade_enabled",
        "today_on",
        "observe_only",
        "paper_mode",
        "daily_loss_limit_pct",
        "streak_stop_enabled",
        "no_paper_hours",
        "start_hour",
        "end_hour",
        "mr_observe_enabled",
        "ai_gate_enabled",
        "trade_notify_daily_reflection_llm_mode",
    ]
    return {k: str(control.get(k, "") or "") for k in keys if k in control}


def build_evidence(
    *,
    main_logs_dir: Path = DEFAULT_LOGS_DIR,
    shadow_logs_dir: Path = DEFAULT_SHADOW_LOGS_DIR,
    mr_logs_dir: Path = DEFAULT_MR_LOGS_DIR,
    reflection_dir: Path = DEFAULT_REFLECTION_DIR,
    control_path: Path = DEFAULT_CONTROL_PATH,
    day8: str = "",
    lookback_days: int = 3,
) -> Dict[str, Any]:
    resolved_day8 = resolve_day8(main_logs_dir, shadow_logs_dir, mr_logs_dir, day8)
    control = _read_control(control_path)
    main_review = _build_daily_trade_review(main_logs_dir, resolved_day8)
    shadow_report = shadow_promotion_report.build_report(
        main_logs_dir=main_logs_dir,
        shadow_logs_dir=shadow_logs_dir,
        lookback_days=int(lookback_days),
        min_mr_rank_a=0,
    )
    mr_paths = mr_observe_summary.resolve_log_paths(mr_logs_dir, None, int(lookback_days))
    mr_summaries: List[Dict[str, Any]] = []
    for path in mr_paths:
        m = re.match(r"trade_log_(\d{8})\.csv$", path.name)
        if not m:
            continue
        mr_summaries.append(mr_observe_summary.build_summary(mr_observe_summary._read_rows(path), day8=m.group(1), tail=0))
    mr_multi = mr_observe_summary.build_multi_day_summary(
        mr_summaries,
        min_days=3,
        min_rank_a=10,
        min_rank_a_trigger=10,
    )
    time_path = time_block_review.resolve_log_path(main_logs_dir, resolved_day8)
    time_review = time_block_review.build_review(
        time_block_review._read_rows(time_path),
        day8=resolved_day8,
        control=control,
    )
    reflection_report = _load_reflection(reflection_dir, resolved_day8)
    reflection = reflection_report.get("reflection") if isinstance(reflection_report.get("reflection"), dict) else {}
    return {
        "generated_at": _now_jst_text(),
        "day8": resolved_day8,
        "lookback_days": int(lookback_days),
        "paths": {
            "main_logs_dir": str(main_logs_dir),
            "shadow_logs_dir": str(shadow_logs_dir),
            "mr_logs_dir": str(mr_logs_dir),
            "reflection_dir": str(reflection_dir),
            "control_path": str(control_path),
        },
        "isolation": {
            "role": "local_llm_advisory_only",
            "vm_writes": False,
            "control_writes": False,
            "service_restarts": False,
            "safe_if_local_down": True,
            "apply_requires_human": True,
        },
        "control_snapshot": _control_subset(control),
        "main_daily": main_review,
        "shadow_promotion": shadow_report,
        "mr_observe": mr_multi,
        "time_block": time_review,
        "reflection": {
            "available": bool(reflection),
            "goal_achieved": bool(reflection.get("goal_achieved")) if isinstance(reflection, dict) else False,
            "sample_confidence": str(reflection.get("sample_confidence", "") or "") if isinstance(reflection, dict) else "",
            "win_notes": list(reflection.get("win_notes") or [])[:3] if isinstance(reflection, dict) else [],
            "loss_notes": list(reflection.get("loss_notes") or [])[:3] if isinstance(reflection, dict) else [],
            "next_day_actions": list(reflection.get("next_day_actions") or [])[:3] if isinstance(reflection, dict) else [],
            "suggested_control_updates": dict(reflection.get("suggested_control_updates") or {}) if isinstance(reflection, dict) else {},
        },
    }


def build_rule_based_recommendations(evidence: Dict[str, Any]) -> Dict[str, Any]:
    main = evidence.get("main_daily") if isinstance(evidence.get("main_daily"), dict) else {}
    shadow = evidence.get("shadow_promotion") if isinstance(evidence.get("shadow_promotion"), dict) else {}
    mr = evidence.get("mr_observe") if isinstance(evidence.get("mr_observe"), dict) else {}
    time_block = evidence.get("time_block") if isinstance(evidence.get("time_block"), dict) else {}
    reflection = evidence.get("reflection") if isinstance(evidence.get("reflection"), dict) else {}

    pnl = _safe_float(main.get("pnl_jpy_sum"), 0.0)
    closed_n = _safe_int(main.get("closed_n"), 0)
    goal_achieved = bool(reflection.get("goal_achieved"))
    shadow_decision = str(shadow.get("decision", "WAIT") or "WAIT")
    mr_decision = str(mr.get("decision", "WAIT") or "WAIT")

    next_steps: List[str] = []
    paper_experiments: List[str] = []
    reject_conditions: List[str] = [
        "LLM提案だけでVMのCONTROL.csvを変更しない",
        "LIVE/main昇格はshadow/observe/PAPERのゲート通過後だけ",
        "ローカルOllama停止時もVMサービスは変更しない",
    ]
    control_proposals: List[Dict[str, Any]] = []

    if shadow_decision != "OK":
        next_steps.append("shadowはmain昇格しない。WAIT/NG理由を消すまで観察継続。")
    else:
        next_steps.append("shadowは昇格候補。ただし人間レビューとPAPER再確認を挟む。")

    if mr_decision == "PAPER_CANDIDATE":
        paper_experiments.append("MR rank A + trigger の専用PAPERを小さく回し、TP/SL/timeoutを3営業日見る。")
    else:
        next_steps.append("MRはobserve継続。rank A trigger件数が閾値を超えるまで実弾化しない。")

    if _safe_int(time_block.get("time_block_n"), 0) > 0:
        next_steps.append("時間ブロックは本体維持。緩める場合は別PAPERで時間帯別に検証。")

    if closed_n <= 1:
        next_steps.append("当日サンプルが薄いので、設定変更よりログ蓄積を優先。")
    elif pnl > 0 and not goal_achieved:
        next_steps.append("プラス終了だが目標未達。利幅拡大より、良い時間帯の再現性を先に確認。")
    elif pnl < 0:
        control_proposals.append(
            {
                "key": "daily_loss_limit_pct",
                "direction": "tighten_candidate",
                "reason": "日次損益がマイナス。反省JSONとshadow悪化が重なる場合だけ候補。",
                "apply": False,
            }
        )

    return {
        "mode": "proposal_only",
        "summary_ja": (
            f"{evidence.get('day8')} は main pnl={pnl:+.0f}円 / closed={closed_n}。"
            f" shadow={shadow_decision}, MR={mr_decision}。ローカルLLMは助言のみ。"
        ),
        "next_safe_steps": next_steps[:6],
        "paper_experiments": paper_experiments[:4],
        "control_proposals": control_proposals,
        "reject_conditions": reject_conditions,
        "confidence": "medium" if closed_n >= 2 else "low",
    }


def _compact_for_prompt(evidence: Dict[str, Any]) -> Dict[str, Any]:
    main = evidence.get("main_daily") if isinstance(evidence.get("main_daily"), dict) else {}
    shadow = evidence.get("shadow_promotion") if isinstance(evidence.get("shadow_promotion"), dict) else {}
    mr = evidence.get("mr_observe") if isinstance(evidence.get("mr_observe"), dict) else {}
    time_block = evidence.get("time_block") if isinstance(evidence.get("time_block"), dict) else {}
    return {
        "day8": evidence.get("day8"),
        "isolation": evidence.get("isolation"),
        "control_snapshot": evidence.get("control_snapshot"),
        "main": {
            "pnl_jpy_sum": main.get("pnl_jpy_sum"),
            "closed_n": main.get("closed_n"),
            "win_rate_pct": main.get("win_rate_pct"),
            "profit_factor_jpy": main.get("profit_factor_jpy"),
            "exit_reason_breakdown": main.get("exit_reason_breakdown"),
            "good_hours": main.get("good_hours"),
            "bad_hours": main.get("bad_hours"),
            "observe_time_block_n": main.get("observe_time_block_n"),
            "observe_ai_block_n": main.get("observe_ai_block_n"),
        },
        "shadow": {
            "decision": shadow.get("decision"),
            "reasons": shadow.get("reasons"),
            "shadow": shadow.get("shadow"),
            "delta": shadow.get("delta"),
        },
        "mr": {
            "decision": mr.get("decision"),
            "reasons": mr.get("reasons"),
            "mr_rank_counts": mr.get("mr_rank_counts"),
            "mr_rank_a_trigger_n": mr.get("mr_rank_a_trigger_n"),
            "mr_rank_signal_counts": mr.get("mr_rank_signal_counts"),
            "mr_rank_hour_counts": mr.get("mr_rank_hour_counts"),
        },
        "time_block": {
            "time_block_n": time_block.get("time_block_n"),
            "time_block_by_hour": time_block.get("time_block_by_hour"),
            "time_block_by_reason": time_block.get("time_block_by_reason"),
            "suggestion": time_block.get("suggestion"),
        },
        "reflection": evidence.get("reflection"),
    }


def build_llm_prompt(evidence: Dict[str, Any], rule_based: Dict[str, Any]) -> str:
    compact = _compact_for_prompt(evidence)
    main = compact.get("main") if isinstance(compact.get("main"), dict) else {}
    shadow = compact.get("shadow") if isinstance(compact.get("shadow"), dict) else {}
    mr = compact.get("mr") if isinstance(compact.get("mr"), dict) else {}
    time_block = compact.get("time_block") if isinstance(compact.get("time_block"), dict) else {}
    reflection = compact.get("reflection") if isinstance(compact.get("reflection"), dict) else {}
    payload = {
        "day8": compact.get("day8"),
        "main": {
            "pnl_jpy_sum": main.get("pnl_jpy_sum"),
            "closed_n": main.get("closed_n"),
            "win_rate_pct": main.get("win_rate_pct"),
            "profit_factor_jpy": main.get("profit_factor_jpy"),
            "exit_reason_breakdown": main.get("exit_reason_breakdown"),
            "observe_time_block_n": main.get("observe_time_block_n"),
            "observe_ai_block_n": main.get("observe_ai_block_n"),
        },
        "shadow": {
            "decision": shadow.get("decision"),
            "reasons": list(shadow.get("reasons") or [])[:3],
        },
        "mr": {
            "decision": mr.get("decision"),
            "reasons": list(mr.get("reasons") or [])[:2],
            "rank_counts": mr.get("mr_rank_counts"),
            "rank_a_trigger_n": mr.get("mr_rank_a_trigger_n"),
        },
        "time_block": {
            "time_block_n": time_block.get("time_block_n"),
            "by_hour": time_block.get("time_block_by_hour"),
            "by_reason": time_block.get("time_block_by_reason"),
        },
        "reflection": {
            "goal_achieved": reflection.get("goal_achieved"),
            "win_notes": list(reflection.get("win_notes") or [])[:2],
            "loss_notes": list(reflection.get("loss_notes") or [])[:2],
        },
        "baseline_next_safe_steps": list(rule_based.get("next_safe_steps") or [])[:4],
    }
    return (
        "あなたはOuroboros trading botのローカル助言専用LLMです。\n"
        "重要: VM実行・通知・ウィジェット・CONTROL.csvへは一切書き戻せません。"
        "提案は observe/shadow/PAPER を優先し、LIVE/main実弾変更を直接指示しないでください。\n"
        "入力を読んで、次のキーだけを持つ短いJSONを返してください。余計な文章は禁止です。\n"
        "reflection や nested object は返さないでください。\n"
        "{\n"
        '  "summary_ja": "目標未達だがmainは小幅プラス。shadowはNGなので昇格しない。",\n'
        '  "next_safe_steps": ["shadowのNG理由が消えるまでmain昇格しない", "MRはA-trigger専用PAPERで3営業日見る"],\n'
        '  "paper_experiments": ["時間ブロック緩和は本体でなく別PAPERで検証する"],\n'
        '  "control_proposals": [{"key":"...", "direction":"...", "reason":"...", "apply": false}],\n'
        '  "reject_conditions": ["やってはいけない条件"],\n'
        '  "confidence": "low|medium|high"\n'
        "}\n\n"
        f"入力データ:\n{json.dumps(payload, ensure_ascii=False, sort_keys=True)}\n"
        "もう一度: JSONのトップレベルキーは summary_ja, next_safe_steps, paper_experiments, control_proposals, reject_conditions, confidence の6つだけ。"
    )


def _csv_tokens(value: str) -> List[str]:
    return [p.strip() for p in str(value or "").split(",") if p.strip()]


def _is_model_match(installed: str, requested: str) -> bool:
    a = str(installed or "").strip()
    b = str(requested or "").strip()
    return bool(a and b and (a == b or a.split(":")[0] == b.split(":")[0]))


def _resolve_installed_model(candidate: str, installed: List[str]) -> str:
    c = str(candidate or "").strip()
    if not c:
        return ""
    if c in installed:
        return c
    if ":" not in c:
        for item in installed:
            if str(item).split(":")[0] == c:
                return str(item)
    return ""


def _model_size_score(model: str) -> float:
    m = re.search(r":(\d+(?:\.\d+)?)b\b", str(model or "").lower())
    if m:
        return float(m.group(1))
    return 999.0


def select_ollama_attempt_models(requested: str, installed: List[str], fallback_models: List[str]) -> List[str]:
    candidates: List[str] = []
    requested = str(requested or "").strip()
    if requested:
        candidates.append(requested)
    candidates.extend([m for m in fallback_models if str(m or "").strip()])
    if installed:
        candidates.extend(sorted(installed, key=_model_size_score))
    out: List[str] = []
    for model in candidates:
        model = str(model or "").strip()
        if not model:
            continue
        if installed:
            model = _resolve_installed_model(model, installed)
        if not model:
            continue
        if model in out:
            continue
        out.append(model)
    return out


def extract_json_object(text: str) -> Dict[str, Any]:
    s = str(text or "").strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    try:
        data = json.loads(s)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass
    start = s.find("{")
    end = s.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(s[start : end + 1])
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _llm_advisory_is_accepted(parsed: Dict[str, Any]) -> bool:
    if not isinstance(parsed, dict) or not parsed:
        return False
    summary = str(parsed.get("summary_ja", "") or "").strip()
    if not summary:
        return False
    safe_steps = parsed.get("next_safe_steps")
    if not isinstance(safe_steps, list) or not safe_steps:
        return False
    blocked_phrases = ("TPを含む決済はNG", "LIVE/main実弾変更", "CONTROL.csvを変更")
    joined = summary + " " + " ".join(str(x) for x in safe_steps)
    if any(p in joined for p in blocked_phrases):
        return False
    placeholders = {
        "observe/shadow/PAPER前提の安全手順",
        "PAPERまたはobserveで試すこと",
        "やってはいけない条件",
    }
    if any(str(step or "").strip() in placeholders for step in safe_steps):
        return False
    for proposal in parsed.get("control_proposals") or []:
        if isinstance(proposal, dict) and proposal.get("apply") is not False:
            return False
    return True


def run_local_llm(
    *,
    prompt: str,
    llm_mode: str,
    ollama_base_url: str,
    ollama_model: str,
    fallback_models: List[str],
    timeout_sec: int,
    max_chars: int,
    num_predict: int = 280,
) -> Dict[str, Any]:
    mode = str(llm_mode or "auto").strip().lower()
    feedback: Dict[str, Any] = {
        "used": False,
        "mode": mode,
        "provider": "ollama",
        "base_url": normalize_ollama_base_url(ollama_base_url),
        "model": str(ollama_model or "").strip(),
        "attempted_models": [],
        "attempt_errors": {},
        "reason": "",
        "error": "",
        "raw_text": "",
        "parsed_json": {},
    }
    if mode == "off":
        feedback["reason"] = "llm_mode=off"
        return feedback
    if mode not in ("auto", "ollama"):
        feedback["reason"] = "unsupported_llm_mode"
        feedback["error"] = f"unsupported llm_mode={mode}"
        return feedback

    installed: List[str] = []
    try:
        installed = list_ollama_models(base_url=str(feedback["base_url"]), timeout_sec=min(5, max(1, int(timeout_sec))))
        feedback["installed_models"] = installed
    except Exception as e:
        feedback["reason"] = "tags_fetch_failed"
        feedback["error"] = str(e)
        if mode == "auto":
            return feedback
    if mode == "auto" and installed == []:
        feedback["reason"] = "no_models_installed"
        return feedback

    attempts = select_ollama_attempt_models(str(ollama_model), installed, fallback_models)
    if not attempts and not installed:
        attempts = [str(ollama_model or DEFAULT_OLLAMA_MODEL)]
    feedback["attempted_models"] = attempts

    for model in attempts:
        try:
            raw = run_ollama_generate_summary(
                base_url=str(feedback["base_url"]),
                model=model,
                prompt=prompt,
                system="提案はJSONのみ。VMやCONTROLへ自動反映する指示は禁止。",
                timeout_sec=max(1, int(timeout_sec)),
                max_chars=0,
                options={
                    "num_predict": max(80, int(num_predict)),
                    "temperature": 0.2,
                    "num_ctx": 2048,
                },
                format_json=True,
            )
            parsed = extract_json_object(raw)
            accepted = _llm_advisory_is_accepted(parsed)
            feedback["used"] = True
            feedback["model"] = model
            feedback["raw_text"] = raw if int(max_chars) <= 0 or len(raw) <= int(max_chars) else raw[: int(max_chars)].rstrip() + "..."
            feedback["raw_text_truncated"] = bool(int(max_chars) > 0 and len(raw) > int(max_chars))
            feedback["parsed_json"] = parsed
            feedback["accepted"] = bool(accepted)
            feedback["reason"] = "ok" if accepted else ("ok_unaccepted" if parsed else "ok_unparsed")
            feedback["error"] = ""
            return feedback
        except Exception as e:
            feedback["attempt_errors"][model] = str(e)
    feedback["reason"] = feedback.get("reason") or "generate_failed"
    feedback["error"] = "; ".join(f"{k}: {v}" for k, v in (feedback.get("attempt_errors") or {}).items())[:800]
    return feedback


def build_report(
    *,
    main_logs_dir: Path = DEFAULT_LOGS_DIR,
    shadow_logs_dir: Path = DEFAULT_SHADOW_LOGS_DIR,
    mr_logs_dir: Path = DEFAULT_MR_LOGS_DIR,
    reflection_dir: Path = DEFAULT_REFLECTION_DIR,
    control_path: Path = DEFAULT_CONTROL_PATH,
    snapshot_dir: Optional[Path] = None,
    day8: str = "",
    lookback_days: int = 3,
    llm_mode: str = "auto",
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL,
    ollama_model: str = DEFAULT_OLLAMA_MODEL,
    ollama_fallback_models: str = "qwen2.5:0.5b,qwen2.5:1.5b",
    timeout_sec: int = 45,
    max_chars: int = 1600,
    num_predict: int = 280,
) -> Dict[str, Any]:
    if snapshot_dir:
        paths = resolve_paths_from_snapshot(snapshot_dir)
        main_logs_dir = paths["logs_dir"]
        shadow_logs_dir = paths["shadow_logs_dir"]
        mr_logs_dir = paths["mr_logs_dir"]
        reflection_dir = paths["reflection_dir"]
        control_path = paths["control_path"]
    evidence = build_evidence(
        main_logs_dir=main_logs_dir,
        shadow_logs_dir=shadow_logs_dir,
        mr_logs_dir=mr_logs_dir,
        reflection_dir=reflection_dir,
        control_path=control_path,
        day8=day8,
        lookback_days=int(lookback_days),
    )
    rule_based = build_rule_based_recommendations(evidence)
    prompt = build_llm_prompt(evidence, rule_based)
    llm_feedback = run_local_llm(
        prompt=prompt,
        llm_mode=llm_mode,
        ollama_base_url=ollama_base_url,
        ollama_model=ollama_model,
        fallback_models=_csv_tokens(ollama_fallback_models),
        timeout_sec=int(timeout_sec),
        max_chars=int(max_chars),
        num_predict=int(num_predict),
    )
    return {
        "version": 1,
        "kind": "local_llm_trade_review",
        "generated_at": _now_jst_text(),
        "safety": {
            "vm_impact": "none",
            "local_down_effect_on_vm": "none",
            "writes_control": False,
            "writes_vm": False,
            "proposal_only": True,
        },
        "evidence": evidence,
        "rule_based_recommendations": rule_based,
        "llm_feedback": llm_feedback,
    }


def format_markdown(report: Dict[str, Any]) -> str:
    evidence = report.get("evidence") if isinstance(report.get("evidence"), dict) else {}
    rec = report.get("rule_based_recommendations") if isinstance(report.get("rule_based_recommendations"), dict) else {}
    llm = report.get("llm_feedback") if isinstance(report.get("llm_feedback"), dict) else {}
    parsed = llm.get("parsed_json") if isinstance(llm.get("parsed_json"), dict) else {}
    lines = [
        f"# Local LLM Trade Review {evidence.get('day8', '')}",
        "",
        "## Safety",
        "- VM impact: none",
        "- CONTROL writes: false",
        "- Service restarts: false",
        "- Local LLM outage: VM unaffected",
        "",
        "## Rule-Based Recommendation",
        f"- {rec.get('summary_ja', '')}",
    ]
    for item in rec.get("next_safe_steps") or []:
        lines.append(f"- next: {item}")
    for item in rec.get("paper_experiments") or []:
        lines.append(f"- paper: {item}")
    accepted = bool(llm.get("accepted"))
    lines.extend(
        [
            "",
            "## LLM Advisory",
            f"- used: {bool(llm.get('used'))}",
            f"- accepted: {accepted}",
            f"- reason: {llm.get('reason', '')}",
            f"- model: {llm.get('model', '')}",
        ]
    )
    if accepted and parsed:
        lines.append(f"- summary: {parsed.get('summary_ja', '')}")
        for item in parsed.get("next_safe_steps") or []:
            lines.append(f"- llm-next: {item}")
    elif bool(llm.get("used")):
        lines.append("- ignored: LLM output was not accepted; using rule-based recommendation only.")
    return "\n".join(lines).rstrip() + "\n"


def write_report_outputs(report: Dict[str, Any], out_dir: Path) -> Tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    day8 = str(((report.get("evidence") or {}).get("day8") if isinstance(report.get("evidence"), dict) else "") or datetime.now().strftime("%Y%m%d"))
    json_path = out_dir / f"local_llm_trade_review_{day8}.json"
    md_path = out_dir / f"local_llm_trade_review_{day8}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(format_markdown(report), encoding="utf-8")
    return json_path, md_path


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Local-only LLM advisory review for Ouroboros trading logs.")
    p.add_argument("--snapshot-dir", default="", help="Use read-only VM snapshot directory produced by sync_vm_llm_inputs.sh.")
    p.add_argument("--logs-dir", default=str(DEFAULT_LOGS_DIR))
    p.add_argument("--shadow-logs-dir", default=str(DEFAULT_SHADOW_LOGS_DIR))
    p.add_argument("--mr-logs-dir", default=str(DEFAULT_MR_LOGS_DIR))
    p.add_argument("--reflection-dir", default=str(DEFAULT_REFLECTION_DIR))
    p.add_argument("--control", default=str(DEFAULT_CONTROL_PATH))
    p.add_argument("--day8", default="")
    p.add_argument("--lookback-days", type=int, default=3)
    p.add_argument("--llm-mode", choices=("off", "auto", "ollama"), default="auto")
    p.add_argument("--ollama-base-url", default=DEFAULT_OLLAMA_BASE_URL)
    p.add_argument("--ollama-model", default=DEFAULT_OLLAMA_MODEL)
    p.add_argument("--ollama-fallback-models", default="qwen2.5:0.5b,qwen2.5:1.5b")
    p.add_argument("--timeout-sec", type=int, default=45)
    p.add_argument("--max-chars", type=int, default=1600)
    p.add_argument("--num-predict", type=int, default=280)
    p.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    p.add_argument("--print-json", action="store_true")
    p.add_argument("--no-write", action="store_true")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    snapshot_dir = Path(str(args.snapshot_dir)).expanduser() if str(args.snapshot_dir or "").strip() else None
    report = build_report(
        main_logs_dir=Path(str(args.logs_dir)).expanduser(),
        shadow_logs_dir=Path(str(args.shadow_logs_dir)).expanduser(),
        mr_logs_dir=Path(str(args.mr_logs_dir)).expanduser(),
        reflection_dir=Path(str(args.reflection_dir)).expanduser(),
        control_path=Path(str(args.control)).expanduser(),
        snapshot_dir=snapshot_dir,
        day8=str(args.day8 or ""),
        lookback_days=int(args.lookback_days),
        llm_mode=str(args.llm_mode),
        ollama_base_url=str(args.ollama_base_url),
        ollama_model=str(args.ollama_model),
        ollama_fallback_models=str(args.ollama_fallback_models),
        timeout_sec=int(args.timeout_sec),
        max_chars=int(args.max_chars),
        num_predict=int(args.num_predict),
    )
    if args.print_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_markdown(report), end="")
    if not bool(args.no_write):
        json_path, md_path = write_report_outputs(report, Path(str(args.out_dir)).expanduser())
        print(f"\n[OK] wrote {json_path}")
        print(f"[OK] wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
