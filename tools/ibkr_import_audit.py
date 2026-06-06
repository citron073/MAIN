#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Set, Union


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCAN_ROOTS = [ROOT, ROOT / "tools", ROOT / "tests"]
ALLOWED_PAPER_IMPORTERS = {"ibkr_bot.py"}


def _now_jst_str() -> str:
    return (datetime.utcnow() + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class ImportHit:
    relpath: str
    module: str
    lineno: int

    def as_dict(self) -> Dict[str, object]:
        return {"path": self.relpath, "module": self.module, "lineno": self.lineno}


def _iter_py_files(scan_roots: Iterable[Path]) -> Iterable[Path]:
    seen: Set[Path] = set()
    for root in scan_roots:
        if not root.exists():
            continue
        if root.is_file() and root.suffix == ".py":
            if root not in seen:
                seen.add(root)
                yield root
            continue
        pattern = "*.py" if root.name != "tests" else "test_*unittest.py"
        walker = root.glob(pattern) if root in {ROOT, ROOT / "tools", ROOT / "tests"} else root.rglob("*.py")
        for path in walker:
            if "__pycache__" in path.parts:
                continue
            if path not in seen:
                seen.add(path)
                yield path


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except Exception:
        return path.name


def _normalize_scan_roots(scan_roots: Union[Path, Iterable[Path]]) -> List[Path]:
    if isinstance(scan_roots, Path):
        return [scan_roots]
    return list(scan_roots)


def collect_import_hits(scan_roots: Union[Path, Iterable[Path]]) -> List[ImportHit]:
    hits: List[ImportHit] = []
    for path in _iter_py_files(_normalize_scan_roots(scan_roots)):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except Exception:
            continue
        rel = _display_path(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in {"ibkr_adapter", "ibkr_paper_adapter"}:
                        hits.append(ImportHit(rel, alias.name, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                if node.module in {"ibkr_adapter", "ibkr_paper_adapter"}:
                    hits.append(ImportHit(rel, str(node.module), node.lineno))
    return hits


def build_audit(scan_roots: Union[Path, Iterable[Path]] = DEFAULT_SCAN_ROOTS) -> Dict[str, object]:
    hits = collect_import_hits(scan_roots)
    readonly_hits = [h for h in hits if h.module == "ibkr_adapter"]
    paper_hits = [h for h in hits if h.module == "ibkr_paper_adapter"]
    unexpected = [h for h in paper_hits if Path(h.relpath).name not in ALLOWED_PAPER_IMPORTERS]
    allowed = [h for h in paper_hits if Path(h.relpath).name in ALLOWED_PAPER_IMPORTERS]

    return {
        "generated_at_jst": _now_jst_str(),
        "paper_order_allowed_importers": sorted(ALLOWED_PAPER_IMPORTERS),
        "paper_order_importers_actual": [h.as_dict() for h in paper_hits],
        "paper_order_importers_allowed": [h.as_dict() for h in allowed],
        "paper_order_importers_unexpected": [h.as_dict() for h in unexpected],
        "read_only_importers_actual": [h.as_dict() for h in readonly_hits],
        "ok": len(unexpected) == 0,
        "next_action": (
            "OK"
            if len(unexpected) == 0
            else "ibkr_paper_adapter の import を許可呼び出し元へ限定する"
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit IBKR adapter imports and allowed paper-order callers.")
    ap.add_argument("--print-json", action="store_true")
    args = ap.parse_args()

    payload = build_audit()
    if args.print_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            "ibkr_import_audit={status} paper_importers={paper} unexpected={unexpected}".format(
                status="OK" if payload["ok"] else "WARN",
                paper=len(payload["paper_order_importers_actual"]),
                unexpected=len(payload["paper_order_importers_unexpected"]),
            )
        )
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
