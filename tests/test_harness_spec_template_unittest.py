from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools import harness_spec_template as mod


class HarnessSpecTemplateTest(unittest.TestCase):
    def test_list_templates_returns_template_names(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            tpl = base / "widget_ui.md"
            tpl.write_text("# Widget UI Spec Template\n\nStatus: READY\n", encoding="utf-8")
            items = mod.list_templates(base)
            self.assertEqual(items[0]["name"], "widget_ui")
            self.assertEqual(items[0]["title"], "Widget UI Spec Template")

    def test_use_template_requires_force_for_existing_current_spec(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            template_dir = root / "templates"
            template_dir.mkdir()
            (template_dir / "widget_ui.md").write_text("# Widget\n\nStatus: READY\n", encoding="utf-8")
            current = root / "current_spec.md"
            current.write_text("# Current\n\nStatus: DRAFT\n", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                mod.use_template("widget_ui", template_dir=template_dir, current_spec_path=current)

            out = mod.use_template("widget_ui", template_dir=template_dir, current_spec_path=current, force=True, backup_dir=root / "backups")
            self.assertEqual(out["copied_to"], str(current))
            self.assertIn("# Widget", current.read_text(encoding="utf-8"))
            self.assertTrue(Path(out["backup_path"]).exists())


if __name__ == "__main__":
    unittest.main()
