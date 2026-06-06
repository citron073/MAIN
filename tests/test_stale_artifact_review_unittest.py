from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import stale_artifact_review as mod


class StaleArtifactReviewTest(unittest.TestCase):
    def test_build_review_marks_named_files_stale_by_age(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            review_out = Path(td)
            (review_out / "stock_shadow_state.json").write_text('{"ok":true}\n', encoding="utf-8")
            (review_out / "signal_scanner_latest.json").write_text(
                '{"generated_at_jst":"2026-05-01 09:00:00","result":"OBSERVE_OK"}\n',
                encoding="utf-8",
            )

            with mock.patch.object(mod, "_age_hours", return_value=30.0):
                payload = mod.build_review(review_out)

            self.assertGreaterEqual(payload["stale_count"], 2)
            paths = {item["path"]: item for item in payload["items"]}
            self.assertEqual(paths[str(review_out / "stock_shadow_state.json")]["status"], "STALE")
            self.assertEqual(paths[str(review_out / "signal_scanner_latest.json")]["status"], "STALE")

    def test_write_outputs_creates_latest_alias(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            review_out = Path(td)
            payload = {
                "generated_at_jst": "2026-05-13 15:00:00",
                "stale_count": 1,
                "archive_candidates": ["review_out/example.json"],
                "items": [{"path": "review_out/example.json", "status": "STALE", "age_hours": 25.0, "reason": "x", "suggested_action": "archive"}],
            }
            paths = mod.write_outputs(payload, review_out)
            latest = Path(paths["latest"])
            self.assertTrue(latest.exists())
            loaded = json.loads(latest.read_text(encoding="utf-8"))
            self.assertEqual(loaded["stale_count"], 1)

    def test_build_review_includes_archive_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            review_out = Path(td)
            for suffix in ("json", "md"):
                (review_out / f"trade_system_review_20260418_010203.{suffix}").write_text("x\n", encoding="utf-8")
            with mock.patch.object(mod, "_age_hours", return_value=48.0):
                payload = mod.build_review(review_out)
            self.assertIn("archive_candidates", payload)
            self.assertEqual(len(payload["archive_candidates"]), 2)


if __name__ == "__main__":
    unittest.main()
