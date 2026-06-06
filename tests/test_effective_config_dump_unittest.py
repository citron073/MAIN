from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools import effective_config_dump as mod


class EffectiveConfigDumpTest(unittest.TestCase):
    def test_build_dump_is_local_only_and_shows_watch_values(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            control = root / "CONTROL.csv"
            ai_model = root / "ai_model.json"
            control.write_text(
                "\n".join(
                    [
                        "key,value",
                        "trade_enabled,1",
                        "today_on,1",
                        "paper_mode,1",
                        "live_enabled,0",
                        "market_phase_enabled,1",
                        "aiba_style_enabled,1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            ai_model.write_text("{}\n", encoding="utf-8")

            obj = mod.build_dump(control_path=control, ai_model_path=ai_model)

        self.assertEqual(obj["source_mode"], "local")
        self.assertTrue(obj["control_exists"])
        self.assertFalse(obj["safety"]["writes_control"])
        self.assertIn("trade_enabled", obj["watch_values"])
        self.assertEqual(obj["raw_control_high_risk"]["trade_enabled"], "1")
        text = mod.format_text(obj)
        self.assertIn("effective_config source=local", text)
        self.assertIn("safety=local_only", text)

    def test_build_dump_can_use_snapshot_layout(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            snapshot = Path(td) / "snapshot"
            main_dir = snapshot / "MAIN"
            main_dir.mkdir(parents=True)
            (main_dir / "CONTROL.csv").write_text("key,value\ntrade_enabled,0\n", encoding="utf-8")
            (main_dir / "ai_model.json").write_text("{}\n", encoding="utf-8")

            obj = mod.build_dump(snapshot_dir=snapshot)

        self.assertEqual(obj["source_mode"], "vm_snapshot")
        self.assertEqual(obj["snapshot_dir"], str(snapshot))
        self.assertTrue(str(obj["control_path"]).endswith("/snapshot/MAIN/CONTROL.csv"))


if __name__ == "__main__":
    unittest.main()
