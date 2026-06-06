#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.trade_system_review import DEFAULT_AI_MODEL_PATH, DEFAULT_CONTROL_PATH, _effective_config, resolve_paths_from_snapshot


WATCH_KEYS = (
    "trade_enabled",
    "today_on",
    "paper_mode",
    "observe_only",
    "live_enabled",
    "rollout_mode",
    "daily_loss_limit_pct",
    "ai_enabled",
    "ai_mode",
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
)


def build_dump(
    *,
    control_path: Path = DEFAULT_CONTROL_PATH,
    ai_model_path: Path = DEFAULT_AI_MODEL_PATH,
    snapshot_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    source_mode = "local"
    resolved_snapshot_dir = ""
    if snapshot_dir is not None and str(snapshot_dir).strip():
        source_mode = "vm_snapshot"
        resolved_snapshot = Path(snapshot_dir).expanduser()
        paths = resolve_paths_from_snapshot(resolved_snapshot)
        control_path = paths["control_path"]
        ai_model_path = paths["ai_model_path"]
        resolved_snapshot_dir = str(resolved_snapshot)

    cfg = _effective_config(Path(control_path).expanduser(), Path(ai_model_path).expanduser())
    values = cfg.get("values") if isinstance(cfg.get("values"), dict) else {}
    watch_values = {key: values.get(key) for key in WATCH_KEYS if key in values}
    return {
        "source_mode": source_mode,
        "snapshot_dir": resolved_snapshot_dir,
        "control_exists": Path(control_path).expanduser().exists(),
        "ai_model_exists": Path(ai_model_path).expanduser().exists(),
        "control_path": str(Path(control_path).expanduser()),
        "ai_model_path": str(Path(ai_model_path).expanduser()),
        "bot_version": cfg.get("bot_version", ""),
        "feature_schema": cfg.get("feature_schema", ""),
        "watch_values": watch_values,
        "raw_control_high_risk": cfg.get("raw_control_high_risk", {}),
        "safety": {
            "local_only": True,
            "writes_control": False,
            "service_restarts": False,
            "external_api": False,
            "secrets_read": False,
        },
    }


def format_text(obj: Dict[str, Any]) -> str:
    lines = [
        f"effective_config source={obj.get('source_mode', 'local')}",
        f"bot_version={obj.get('bot_version', '-')}",
        f"feature_schema={obj.get('feature_schema', '-')}",
        f"control={obj.get('control_path', '-')}",
        f"ai_model={obj.get('ai_model_path', '-')}",
        f"exists=control:{bool(obj.get('control_exists'))} ai_model:{bool(obj.get('ai_model_exists'))}",
        "safety=local_only writes_control:false service_restarts:false external_api:false secrets_read:false",
        "",
        "[watch_values]",
    ]
    values = obj.get("watch_values") if isinstance(obj.get("watch_values"), dict) else {}
    for key in sorted(values):
        lines.append(f"{key}={values[key]}")
    raw = obj.get("raw_control_high_risk") if isinstance(obj.get("raw_control_high_risk"), dict) else {}
    if raw:
        lines.extend(["", "[raw_control_high_risk]"])
        for key in sorted(raw):
            lines.append(f"{key}={raw[key]}")
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Print effective Ouroboros runtime config without writing CONTROL or restarting services.")
    p.add_argument("--snapshot-dir", default="", help="Use read-only VM snapshot layout from .local_llm/vm_snapshot/latest.")
    p.add_argument("--control-path", default=str(DEFAULT_CONTROL_PATH))
    p.add_argument("--ai-model-path", default=str(DEFAULT_AI_MODEL_PATH))
    p.add_argument("--print-json", action="store_true")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    obj = build_dump(
        control_path=Path(args.control_path),
        ai_model_path=Path(args.ai_model_path),
        snapshot_dir=Path(args.snapshot_dir) if str(args.snapshot_dir or "").strip() else None,
    )
    if args.print_json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    else:
        print(format_text(obj))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
