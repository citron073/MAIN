from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools import ibkr_import_audit as mod


class IbkrImportAuditTest(unittest.TestCase):
    def test_build_audit_allows_only_ibkr_bot_for_paper_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "ibkr_bot.py").write_text("from ibkr_paper_adapter import IBKRPaperAdapter\n", encoding="utf-8")
            (root / "test_ibkr_connection.py").write_text("from ibkr_adapter import IBKRAdapter\n", encoding="utf-8")
            payload = mod.build_audit([root])
            self.assertTrue(payload["ok"])
            self.assertEqual(len(payload["paper_order_importers_unexpected"]), 0)
            self.assertEqual(len(payload["paper_order_importers_actual"]), 1)

    def test_build_audit_flags_unexpected_paper_importer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "ibkr_bot.py").write_text("from ibkr_paper_adapter import IBKRPaperAdapter\n", encoding="utf-8")
            (root / "rogue.py").write_text("from ibkr_paper_adapter import IBKRPaperAdapter\n", encoding="utf-8")
            payload = mod.build_audit([root])
            self.assertFalse(payload["ok"])
            self.assertEqual(len(payload["paper_order_importers_unexpected"]), 1)
            self.assertEqual(payload["paper_order_importers_unexpected"][0]["path"], "rogue.py")

    def test_build_audit_accepts_single_root_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "test_ibkr_connection.py").write_text("from ibkr_adapter import IBKRAdapter\n", encoding="utf-8")
            payload = mod.build_audit(root)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["next_action"], "OK")

    def test_build_audit_allows_no_paper_order_importers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "ibkr_bot.py").write_text("from ibkr_adapter import IBKRAdapter\n", encoding="utf-8")
            payload = mod.build_audit([root])
            self.assertTrue(payload["ok"])
            self.assertEqual(len(payload["paper_order_importers_actual"]), 0)


if __name__ == "__main__":
    unittest.main()
