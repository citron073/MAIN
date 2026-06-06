from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools import react_frontend_harness_check as mod


def _write_package(root: Path, scripts: dict[str, str]) -> None:
    (root / "package.json").write_text(
        json.dumps({"scripts": scripts}, ensure_ascii=False),
        encoding="utf-8",
    )


class ReactFrontendHarnessCheckTest(unittest.TestCase):
    def test_next_project_warns_but_does_not_require_vite_migration(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app").mkdir()
            (root / "components").mkdir()
            (root / "lib").mkdir()
            (root / "next.config.mjs").write_text("export default {}\n", encoding="utf-8")
            _write_package(root, {"build": "next build", "lint": "next lint"})

            result = mod.run_check(root)

            self.assertTrue(result["ok"])
            self.assertEqual(result["kind"], "next")
            codes = [item["code"] for item in result["items"]]
            self.assertIn("next_project", codes)
            self.assertIn("script_missing", codes)
            self.assertNotIn("vite_structure_missing", codes)

    def test_vite_project_checks_recommended_directories(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "vite.config.ts").write_text("export default {}\n", encoding="utf-8")
            for rel in mod.VITE_CORE_DIRS:
                (root / rel).mkdir(parents=True)
            _write_package(root, {"build": "vite build", "lint": "eslint .", "typecheck": "tsc --noEmit", "test": "vitest run"})

            result = mod.run_check(root, strict=True)

            self.assertTrue(result["ok"])
            self.assertEqual(result["kind"], "vite")
            self.assertEqual(result["error_count"], 0)
            self.assertEqual(result["warn_count"], 0)

    def test_vite_strict_flags_missing_directory_as_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "vite.config.ts").write_text("export default {}\n", encoding="utf-8")
            (root / "src").mkdir()
            _write_package(root, {"build": "vite build"})

            result = mod.run_check(root, strict=True)

            self.assertFalse(result["ok"])
            self.assertEqual(result["kind"], "vite")
            self.assertGreater(result["error_count"], 0)
            self.assertIn("vite_structure_missing", {item["code"] for item in result["items"]})


if __name__ == "__main__":
    unittest.main()
