import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import ibkr_prebrief_agent as prebrief_mod
from tools import ibkr_session_review_agent as review_mod


class IbkrSubagentsOutputTest(unittest.TestCase):
    def test_prebrief_writes_latest_json_for_insufficient_data(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            with mock.patch.object(prebrief_mod, "OUT_DIR", out_dir), \
                mock.patch.object(prebrief_mod, "LATEST_PATH", out_dir / "prebrief_latest.json"), \
                mock.patch.object(prebrief_mod, "_load_trade_pairs", return_value=[]):
                rc = prebrief_mod.main(["--logs-dir", td, "--no-ntfy"])
            self.assertEqual(rc, 0)
            latest = out_dir / "prebrief_latest.json"
            self.assertTrue(latest.exists())
            payload = json.loads(latest.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "insufficient_data")
            self.assertEqual(payload["trade_count"], 0)

    def test_review_writes_latest_json_for_missing_log(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            with mock.patch.object(review_mod, "OUT_DIR", out_dir), \
                mock.patch.object(review_mod, "LATEST_PATH", out_dir / "review_latest.json"):
                rc = review_mod.main(["--day", "20260507", "--logs-dir", td, "--no-ntfy"])
            self.assertEqual(rc, 0)
            latest = out_dir / "review_latest.json"
            self.assertTrue(latest.exists())
            payload = json.loads(latest.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "no_data")
            self.assertEqual(payload["day8"], "20260507")
            self.assertFalse(payload["summary"]["found"])


if __name__ == "__main__":
    unittest.main()
