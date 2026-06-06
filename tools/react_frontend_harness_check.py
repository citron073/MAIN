#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_FRONTEND_ROOT = ROOT_DIR / "action_reader" / "frontend"
RECOMMENDED_PACKAGE_SCRIPTS = ("build", "lint", "typecheck", "test")
NEXT_CORE_DIRS = ("app", "components", "lib")
VITE_CORE_DIRS = (
    "src/pages",
    "src/components/ui",
    "src/components/feature",
    "src/lib",
    "src/services",
    "src/types",
)


@dataclass(frozen=True)
class CheckItem:
    level: str
    code: str
    message: str

    def as_dict(self) -> Dict[str, str]:
        return {"level": self.level, "code": self.code, "message": self.message}


def _has_any(root: Path, patterns: Sequence[str]) -> bool:
    for pattern in patterns:
        if any(root.glob(pattern)):
            return True
    return False


def detect_frontend_kind(root: Path) -> str:
    root = Path(root)
    if _has_any(root, ("vite.config.*",)):
        return "vite"
    if _has_any(root, ("next.config.*",)) or (root / "app").exists():
        return "next"
    if (root / "src").exists() or (root / "package.json").exists():
        return "react-unknown"
    return "missing"


def _read_package_json(root: Path) -> Dict[str, Any]:
    path = root / "package.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"__invalid__": True}
    return data if isinstance(data, dict) else {"__invalid__": True}


def run_check(root: Path = DEFAULT_FRONTEND_ROOT, *, strict: bool = False) -> Dict[str, Any]:
    root = Path(root)
    items: List[CheckItem] = []
    kind = detect_frontend_kind(root)

    if kind == "missing":
        items.append(CheckItem("ERROR", "frontend_missing", f"frontend root not found or empty: {root}"))
    elif kind == "next":
        items.append(CheckItem("INFO", "next_project", "Next.js project detected; keep app/ structure and do not migrate to Vite without approval"))
        for rel in NEXT_CORE_DIRS:
            if not (root / rel).exists():
                items.append(CheckItem("WARN", "next_structure_missing", f"Next.js project is missing recommended directory: {rel}"))
    elif kind == "vite":
        for rel in VITE_CORE_DIRS:
            if not (root / rel).exists():
                level = "ERROR" if strict else "WARN"
                items.append(CheckItem(level, "vite_structure_missing", f"Vite project is missing recommended directory: {rel}"))
    else:
        items.append(CheckItem("WARN", "react_unknown", "React-like project detected but framework is not clear; document structure in current_spec.md"))

    pkg = _read_package_json(root)
    scripts = pkg.get("scripts", {}) if isinstance(pkg.get("scripts"), dict) else {}
    if pkg.get("__invalid__"):
        items.append(CheckItem("ERROR", "package_json_invalid", "package.json is not valid JSON"))
    elif not pkg:
        items.append(CheckItem("WARN", "package_json_missing", "package.json is missing"))
    else:
        missing_scripts = [name for name in RECOMMENDED_PACKAGE_SCRIPTS if name not in scripts]
        for name in missing_scripts:
            level = "ERROR" if strict else "WARN"
            items.append(CheckItem(level, "script_missing", f"package.json script missing: {name}"))

    error_count = sum(1 for item in items if item.level == "ERROR")
    warn_count = sum(1 for item in items if item.level == "WARN")
    return {
        "ok": error_count == 0,
        "root": str(root),
        "kind": kind,
        "error_count": error_count,
        "warn_count": warn_count,
        "items": [item.as_dict() for item in items],
    }


def format_text(result: Dict[str, Any]) -> str:
    lines = [
        f"react_frontend_harness={ 'OK' if result.get('ok') else 'NG' } "
        f"kind={result.get('kind')} errors={result.get('error_count')} warnings={result.get('warn_count')}"
    ]
    lines.append(f"root={result.get('root')}")
    for item in result.get("items", []):
        lines.append(f"[{item.get('level')}] {item.get('code')}: {item.get('message')}")
    return "\n".join(lines)


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Check React/Next/Vite frontend structure for the lightweight AI harness.")
    p.add_argument("--root", default=str(DEFAULT_FRONTEND_ROOT), help="Frontend project root.")
    p.add_argument("--strict", action="store_true", help="Treat missing recommended Vite dirs/scripts as errors.")
    p.add_argument("--print-json", action="store_true")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    result = run_check(Path(args.root), strict=bool(args.strict))
    if args.print_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_text(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
