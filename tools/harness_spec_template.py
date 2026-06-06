#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ROOT_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT_DIR / "docs" / "ai_harness" / "spec_templates"
CURRENT_SPEC_PATH = ROOT_DIR / "docs" / "ai_harness" / "current_spec.md"
BACKUP_DIR = ROOT_DIR / ".harness" / "spec_backups"


def _template_files(template_dir: Path = TEMPLATE_DIR) -> Dict[str, Path]:
    if not template_dir.exists():
        return {}
    out: Dict[str, Path] = {}
    for path in sorted(template_dir.glob("*.md")):
        out[path.stem] = path
    return out


def list_templates(template_dir: Path = TEMPLATE_DIR) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for name, path in _template_files(template_dir).items():
        title = path.read_text(encoding="utf-8", errors="ignore").splitlines()[0].lstrip("# ").strip() if path.exists() else name
        out.append({"name": name, "path": str(path), "title": title})
    return out


def _backup_current_spec(current_spec_path: Path, backup_dir: Path = BACKUP_DIR) -> Optional[Path]:
    if not current_spec_path.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{current_spec_path.stem}.{stamp}{current_spec_path.suffix}"
    shutil.copyfile(current_spec_path, backup_path)
    return backup_path


def use_template(
    name: str,
    *,
    template_dir: Path = TEMPLATE_DIR,
    current_spec_path: Path = CURRENT_SPEC_PATH,
    force: bool = False,
    backup: bool = True,
    backup_dir: Path = BACKUP_DIR,
) -> Dict[str, str]:
    templates = _template_files(template_dir)
    key = str(name or "").strip()
    if key not in templates:
        available = ", ".join(sorted(templates)) or "(none)"
        raise KeyError(f"unknown template: {key}; available: {available}")
    if current_spec_path.exists() and not force:
        text = current_spec_path.read_text(encoding="utf-8", errors="ignore")
        if "Status: READY" in text or "Status: DRAFT" in text:
            raise FileExistsError(f"{current_spec_path} already exists; pass --force to replace it")
    current_spec_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = _backup_current_spec(current_spec_path, backup_dir=backup_dir) if force and backup else None
    shutil.copyfile(templates[key], current_spec_path)
    return {
        "copied_to": str(current_spec_path),
        "template": key,
        "backup_path": str(backup_path or ""),
    }


def format_templates(items: List[Dict[str, str]]) -> str:
    if not items:
        return "no templates found"
    lines = ["available_templates:"]
    for item in items:
        lines.append(f"- {item['name']}: {item['title']}")
    return "\n".join(lines)


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="List or copy Ouroboros AI harness spec templates.")
    p.add_argument("--list", action="store_true", help="List available templates.")
    p.add_argument("--use", default="", help="Copy a template into docs/ai_harness/current_spec.md.")
    p.add_argument("--force", action="store_true", help="Replace current_spec.md when using a template.")
    p.add_argument("--no-backup", action="store_true", help="Do not backup current_spec.md before --force replacement.")
    p.add_argument("--print-json", action="store_true")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    if args.use:
        try:
            payload = use_template(str(args.use), force=bool(args.force), backup=not bool(args.no_backup))
        except Exception as e:
            print(f"[ERROR] {e}")
            return 1
        if args.print_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"Copied template '{payload['template']}' -> {payload['copied_to']}")
            if payload.get("backup_path"):
                print(f"Backup: {payload['backup_path']}")
        return 0

    items = list_templates()
    if args.print_json:
        print(json.dumps({"templates": items}, ensure_ascii=False, indent=2))
    else:
        print(format_templates(items))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
