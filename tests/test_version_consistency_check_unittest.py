from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools import version_consistency_check as mod


def _write_fixture(root: Path, *, bot_version: str = "2026.05.05.3", schema: str = "schema-v1") -> None:
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "bot.py").write_text(
        f'OUROBOROS_BOT_VERSION = "{bot_version}"\n'
        f'OUROBOROS_FEATURE_SCHEMA_VERSION = "{schema}"\n',
        encoding="utf-8",
    )
    (root / "HANDOVER.json").write_text(
        '{"versions":{"bot_logic":"%s","feature_schema":"%s"}}\n' % (bot_version, schema),
        encoding="utf-8",
    )
    (root / "docs" / "OUROBOROS_TRADING_SPEC_TABLE.md").write_text(
        f"bot `{bot_version}` schema `{schema}`\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_live_logic_unittest.py").write_text(
        f'expected_schema = "{schema}"\n',
        encoding="utf-8",
    )
    (root / "tests" / "test_widget_status_unittest.py").write_text(
        f'expected_bot = "{bot_version}"\nexpected_schema = "{schema}"\n',
        encoding="utf-8",
    )


class VersionConsistencyCheckTest(unittest.TestCase):
    def test_passes_when_all_files_match_bot_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_fixture(root)
            result = mod.run_version_consistency_check(root)
            self.assertTrue(result["ok"], result)

    def test_fails_when_handover_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_fixture(root)
            (root / "HANDOVER.json").write_text(
                '{"versions":{"bot_logic":"2026.01.01.1","feature_schema":"schema-v1"}}\n',
                encoding="utf-8",
            )
            result = mod.run_version_consistency_check(root)
            self.assertFalse(result["ok"], result)
            self.assertTrue(any(item["path"] == "HANDOVER.json" and item["field"] == "bot_logic" for item in result["items"] if not item["ok"]), result)

    def test_fails_when_test_expectation_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_fixture(root)
            (root / "tests" / "test_live_logic_unittest.py").write_text(
                'expected_bot = "2026.05.05.3"\nexpected_schema = "old-schema"\n',
                encoding="utf-8",
            )
            result = mod.run_version_consistency_check(root)
            self.assertFalse(result["ok"], result)
            self.assertTrue(any(item["path"].endswith("test_live_logic_unittest.py") and item["field"] == "feature_schema" for item in result["items"] if not item["ok"]), result)


if __name__ == "__main__":
    unittest.main()
