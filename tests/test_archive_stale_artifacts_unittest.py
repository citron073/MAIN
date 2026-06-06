from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools import archive_stale_artifacts as mod


class ArchiveStaleArtifactsTest(unittest.TestCase):
    def test_build_archive_plan_collects_existing_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            review_out = root / "review_out"
            review_out.mkdir(parents=True, exist_ok=True)
            legacy = review_out / "trade_system_review_20260418_010203.json"
            legacy.write_text("{}", encoding="utf-8")
            (review_out / "stale_artifact_review_latest.json").write_text(
                json.dumps({"archive_candidates": ["review_out/trade_system_review_20260418_010203.json"]}),
                encoding="utf-8",
            )

            old_root = mod.ROOT
            try:
                mod.ROOT = root
                plan = mod.build_archive_plan(review_out)
            finally:
                mod.ROOT = old_root

            self.assertEqual(plan["candidate_count"], 1)
            self.assertIn("review_out/trade_system_review_20260418_010203.json", plan["candidates"])

    def test_apply_archive_moves_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            review_out = root / "review_out"
            review_out.mkdir(parents=True, exist_ok=True)
            legacy = review_out / "trade_system_review_20260418_010203.json"
            legacy.write_text("{}", encoding="utf-8")
            plan = {
                "generated_at_jst": "2026-05-13 12:00:00",
                "candidate_count": 1,
                "candidates": ["review_out/trade_system_review_20260418_010203.json"],
                "dry_run": True,
            }
            old_root = mod.ROOT
            try:
                mod.ROOT = root
                applied = mod.apply_archive(plan, review_out)
            finally:
                mod.ROOT = old_root

            self.assertFalse(legacy.exists())
            self.assertEqual(len(applied["moved"]), 1)
            self.assertIn("review_out/archive/", applied["moved"][0])

    def test_write_plan_writes_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            review_out = Path(td) / "review_out"
            review_out.mkdir(parents=True, exist_ok=True)
            plan = {
                "generated_at_jst": "2026-05-14 21:00:00",
                "review_path": "review_out/stale_artifact_review_latest.json",
                "archive_dir": "review_out/archive",
                "candidate_count": 1,
                "candidates": ["review_out/trade_system_review_20260418_010203.json"],
                "dry_run": True,
                "terminal_only": True,
                "apply_command": "python3 tools/archive_stale_artifacts.py --apply",
            }
            paths = mod.write_plan(plan, review_out)
            self.assertTrue(Path(paths["json"]).exists())
            self.assertTrue(Path(paths["latest"]).exists())
            self.assertTrue(Path(paths["md"]).exists())
            self.assertTrue(Path(paths["md_latest"]).exists())
            md_text = Path(paths["md_latest"]).read_text(encoding="utf-8")
            self.assertIn("# Archive Stale Artifacts Plan", md_text)
            self.assertIn("generated_at_jst: 2026-05-14 21:00:00", md_text)
            self.assertIn("review_out/trade_system_review_20260418_010203.json", md_text)


if __name__ == "__main__":
    unittest.main()
