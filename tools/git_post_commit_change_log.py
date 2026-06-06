#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List


def _run_git(args: List[str], cwd: Path) -> str:
    p = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {p.stderr.strip()}")
    return str(p.stdout or "").strip()


def _read_app_version(main_dir: Path) -> str:
    p = main_dir / "dashboard.py"
    if not p.exists():
        return "unknown"
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return "unknown"
    m = re.search(r'^\s*APP_VERSION\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    if not m:
        return "unknown"
    return str(m.group(1)).strip() or "unknown"


def _classify_change(files: List[str]) -> str:
    if not files:
        return "CODE"
    lower = [f.lower() for f in files]
    if all(f.endswith(".md") for f in lower):
        return "DOC"
    if any("control.csv" in f for f in lower):
        return "CONFIG"
    if any(f.startswith("tools/") for f in lower):
        return "INFRA"
    return "CODE"


def _git_dirty_count(main_dir: Path) -> int:
    out = _run_git(["status", "--porcelain"], main_dir)
    if not out:
        return 0
    return len([ln for ln in out.splitlines() if ln.strip()])


def build_row(main_dir: Path, author: str | None) -> Dict[str, object]:
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], main_dir)
    commit = _run_git(["rev-parse", "--short", "HEAD"], main_dir)
    summary = _run_git(["show", "-s", "--format=%s", "HEAD"], main_dir)
    ts = _run_git(["show", "-s", "--date=format:%Y-%m-%d %H:%M:%S", "--format=%cd", "HEAD"], main_dir)
    file_lines = _run_git(["show", "--name-only", "--pretty=format:", "HEAD"], main_dir)
    files_rel = [ln.strip() for ln in file_lines.splitlines() if ln.strip()]
    files = [f"MAIN/{f}" for f in files_rel][:200]
    row_type = _classify_change(files_rel)
    log_author = (author or os.getenv("GIT_AUTHOR_NAME") or os.getenv("USER") or "git-hook").strip()
    return {
        "ts": ts,
        "version": _read_app_version(main_dir),
        "type": row_type,
        "author": log_author,
        "summary": f"git commit: {summary}",
        "files": files,
        "git_branch": branch,
        "git_commit": commit,
        "git_dirty_files": _git_dirty_count(main_dir),
        "source": "git.post-commit",
    }


def _is_duplicate_commit_row(path: Path, row: Dict[str, object]) -> bool:
    if not path.exists():
        return False
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return False
    for ln in reversed(lines[-50:]):
        s = ln.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        if str(obj.get("source", "")) != "git.post-commit":
            continue
        return (
            str(obj.get("git_commit", "")) == str(row.get("git_commit", ""))
            and str(obj.get("git_branch", "")) == str(row.get("git_branch", ""))
        )
    return False


def append_row(main_dir: Path, row: Dict[str, object], dry_run: bool) -> Path:
    out = main_dir / ".streamlit" / "dashboard_change_log.jsonl"
    if dry_run:
        print(json.dumps(row, ensure_ascii=False))
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    if _is_duplicate_commit_row(out, row):
        return out
    with open(out, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Append git commit entry to dashboard change log.")
    ap.add_argument("--main-dir", default="", help="Path to MAIN repository root")
    ap.add_argument("--author", default="", help="Override author")
    ap.add_argument("--dry-run", action="store_true", help="Print row instead of writing")
    args = ap.parse_args()

    if str(os.getenv("OUROBOROS_AUTO_CHANGELOG", "1")).strip() in ("0", "false", "False", "off"):
        return 0

    if args.main_dir:
        main_dir = Path(args.main_dir).expanduser().resolve()
    else:
        main_dir = Path(__file__).resolve().parents[1]

    try:
        row = build_row(main_dir, args.author)
        out = append_row(main_dir, row, dry_run=bool(args.dry_run))
    except Exception as e:
        print(f"[WARN] git_post_commit_change_log failed: {e}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"[DRYRUN] target={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
