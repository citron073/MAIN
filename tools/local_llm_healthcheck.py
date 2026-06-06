#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.llm_provider import list_ollama_models, normalize_ollama_base_url


DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:1.5b"
DEFAULT_FALLBACK_MODELS = "qwen2.5:0.5b,qwen2.5:1.5b,llama3.2:1b"


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _csv_tokens(value: str) -> List[str]:
    return [p.strip() for p in str(value or "").split(",") if p.strip()]


def _model_size_score(model: str) -> float:
    m = re.search(r":(\d+(?:\.\d+)?)b\b", str(model or "").lower())
    if m:
        return float(m.group(1))
    return 999.0


def _model_base(model: str) -> str:
    return str(model or "").strip().split(":")[0]


def _resolve_model(candidate: str, installed: List[str]) -> str:
    c = str(candidate or "").strip()
    if not c:
        return ""
    if c in installed:
        return c
    base = _model_base(c)
    for model in installed:
        if _model_base(model) == base:
            return model
    return ""


def choose_model(preferred_model: str, fallback_models: List[str], installed_models: List[str]) -> str:
    installed = [str(m).strip() for m in installed_models if str(m).strip()]
    candidates = [str(preferred_model or "").strip()] + [str(m).strip() for m in fallback_models if str(m).strip()]
    candidates.extend(sorted(installed, key=_model_size_score))
    for candidate in candidates:
        resolved = _resolve_model(candidate, installed)
        if resolved:
            return resolved
    return ""


def build_healthcheck(
    *,
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
    preferred_model: str = DEFAULT_MODEL,
    fallback_models: Optional[List[str]] = None,
    timeout_sec: int = 5,
) -> Dict[str, Any]:
    fallback_models = fallback_models if fallback_models is not None else _csv_tokens(DEFAULT_FALLBACK_MODELS)
    out: Dict[str, Any] = {
        "generated_at": _now_text(),
        "kind": "local_llm_healthcheck",
        "provider": "ollama",
        "base_url": normalize_ollama_base_url(base_url),
        "preferred_model": str(preferred_model or "").strip(),
        "fallback_models": list(fallback_models),
        "reachable": False,
        "installed_models": [],
        "selected_model": "",
        "status": "WARN",
        "reason": "",
        "error": "",
        "isolation": {
            "vm_impact": "none",
            "safe_if_unavailable": True,
            "review_fallback": "rule_based",
        },
        "next_commands": [],
    }
    try:
        installed = list_ollama_models(base_url=str(out["base_url"]), timeout_sec=max(1, int(timeout_sec)))
        out["reachable"] = True
        out["installed_models"] = installed
    except Exception as e:
        out["reason"] = "ollama_unreachable"
        out["error"] = str(e)
        out["next_commands"] = [
            "ollama serve",
            f"ollama pull {out['preferred_model'] or DEFAULT_MODEL}",
        ]
        return out

    selected = choose_model(str(out["preferred_model"]), list(fallback_models), list(out["installed_models"]))
    out["selected_model"] = selected
    if selected:
        out["status"] = "OK"
        out["reason"] = "selected_model_available"
    else:
        out["reason"] = "no_supported_model_installed"
        out["next_commands"] = [f"ollama pull {out['preferred_model'] or DEFAULT_MODEL}"]
    return out


def format_text(result: Dict[str, Any]) -> str:
    lines = [
        f"local_llm_health={result.get('status')} provider={result.get('provider')} reachable={result.get('reachable')}",
        f"base_url={result.get('base_url')}",
        f"selected_model={result.get('selected_model') or '-'} preferred={result.get('preferred_model') or '-'}",
        f"installed_models={','.join(result.get('installed_models') or []) or '-'}",
        f"reason={result.get('reason') or '-'}",
        "vm_impact=none safe_if_unavailable=true",
    ]
    if result.get("error"):
        lines.append(f"error={result.get('error')}")
    if result.get("next_commands"):
        lines.append("next_commands=" + " ; ".join(str(x) for x in result.get("next_commands") or []))
    return "\n".join(lines)


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Check local Ollama availability for local-only Ouroboros reviews.")
    p.add_argument("--base-url", default=DEFAULT_OLLAMA_BASE_URL)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--fallback-models", default=DEFAULT_FALLBACK_MODELS)
    p.add_argument("--timeout-sec", type=int, default=5)
    p.add_argument("--fail-on-unavailable", action="store_true")
    p.add_argument("--print-json", action="store_true")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    result = build_healthcheck(
        base_url=str(args.base_url),
        preferred_model=str(args.model),
        fallback_models=_csv_tokens(str(args.fallback_models)),
        timeout_sec=int(args.timeout_sec),
    )
    if args.print_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_text(result))
    if bool(args.fail_on_unavailable) and result.get("status") != "OK":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
