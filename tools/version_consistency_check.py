#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


ROOT_DIR = Path(__file__).resolve().parents[1]
BOT_PATH = Path("bot.py")
HANDOVER_JSON_PATH = Path("HANDOVER.json")
SPEC_TABLE_PATH = Path("docs/OUROBOROS_TRADING_SPEC_TABLE.md")
LIVE_TEST_PATH = Path("tests/test_live_logic_unittest.py")
WIDGET_TEST_PATH = Path("tests/test_widget_status_unittest.py")


@dataclass(frozen=True)
class VersionCheckItem:
    path: str
    field: str
    expected: str
    actual: str
    ok: bool

    def as_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "field": self.field,
            "expected": self.expected,
            "actual": self.actual,
            "ok": self.ok,
        }


def _read_text(root: Path, rel: Path) -> str:
    return (root / rel).read_text(encoding="utf-8")


def _extract_bot_versions(root: Path) -> Dict[str, str]:
    contract_path = root / "ouroboros_contract.py"
    if contract_path.exists():
        try:
            spec = importlib.util.spec_from_file_location("ouroboros_contract_for_check", contract_path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)  # type: ignore[union-attr]
                bot_version = getattr(module, "OUROBOROS_BOT_VERSION", "")
                schema_version = getattr(module, "OUROBOROS_FEATURE_SCHEMA_VERSION", "")
                if bot_version and schema_version:
                    return {
                        "bot_logic": str(bot_version),
                        "feature_schema": str(schema_version),
                    }
        except Exception:
            pass

    text = _read_text(root, BOT_PATH)
    out: Dict[str, str] = {}
    patterns = {
        "bot_logic": r'OUROBOROS_BOT_VERSION\s*=\s*"([^"]+)"',
        "feature_schema": r'OUROBOROS_FEATURE_SCHEMA_VERSION\s*=\s*"([^"]+)"',
    }
    for key, pattern in patterns.items():
        m = re.search(pattern, text)
        if not m:
            raise ValueError(f"{BOT_PATH} missing {key} declaration")
        out[key] = m.group(1)
    return out


def _contains(root: Path, rel: Path, value: str) -> str:
    if not (root / rel).exists():
        return "<missing>"
    text = _read_text(root, rel)
    return value if value in text else "<not found>"


def run_version_consistency_check(root: Path = ROOT_DIR) -> Dict[str, Any]:
    root = Path(root)
    expected = _extract_bot_versions(root)
    items: List[VersionCheckItem] = []

    handover_actual: Dict[str, str] = {}
    if (root / HANDOVER_JSON_PATH).exists():
        obj = json.loads(_read_text(root, HANDOVER_JSON_PATH))
        versions = obj.get("versions", {}) if isinstance(obj.get("versions"), dict) else {}
        handover_actual = {
            "bot_logic": str(versions.get("bot_logic", "")),
            "feature_schema": str(versions.get("feature_schema", "")),
        }
    else:
        handover_actual = {"bot_logic": "<missing>", "feature_schema": "<missing>"}

    for key, want in expected.items():
        got = handover_actual.get(key, "")
        items.append(VersionCheckItem(str(HANDOVER_JSON_PATH), key, want, got, got == want))

    required_by_path = {
        SPEC_TABLE_PATH: ("bot_logic", "feature_schema"),
        LIVE_TEST_PATH: ("feature_schema",),
        WIDGET_TEST_PATH: ("bot_logic", "feature_schema"),
    }
    for rel, fields in required_by_path.items():
        for key in fields:
            want = expected[key]
            got = _contains(root, rel, want)
            items.append(VersionCheckItem(str(rel), key, want, got, got == want))

    ok = all(item.ok for item in items)
    return {
        "ok": ok,
        "expected": expected,
        "items": [item.as_dict() for item in items],
        "error_count": sum(1 for item in items if not item.ok),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Check bot version/schema consistency across docs and tests.")
    ap.add_argument("--json", action="store_true", help="Print JSON output")
    args = ap.parse_args()

    result = run_version_consistency_check(ROOT_DIR)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        status = "OK" if result["ok"] else "NG"
        exp = result["expected"]
        print(
            "version_consistency={status} bot={bot} schema={schema} errors={errors}".format(
                status=status,
                bot=exp.get("bot_logic", "-"),
                schema=exp.get("feature_schema", "-"),
                errors=result.get("error_count", 0),
            )
        )
        for item in result["items"]:
            if item["ok"]:
                continue
            print(
                "[ERROR] {path} {field}: expected={expected} actual={actual}".format(
                    path=item["path"],
                    field=item["field"],
                    expected=item["expected"],
                    actual=item["actual"],
                )
            )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
