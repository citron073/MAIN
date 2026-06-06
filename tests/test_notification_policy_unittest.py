from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools import notification_policy as mod


class NotificationPolicyTest(unittest.TestCase):
    def test_build_headers_uses_level_priority_and_tags(self) -> None:
        headers = mod.build_ntfy_headers(
            "Warn Title",
            level=mod.LEVEL_WARN,
            tags="shadow_weekly,warning",
            bearer="token-123",
        )
        self.assertEqual(headers["Priority"], "high")
        self.assertEqual(headers["Authorization"], "Bearer token-123")
        self.assertEqual(headers["Title"], "Warn Title")
        self.assertEqual(headers["Tags"], "warning,shadow_weekly")

    def test_cooldown_blocks_until_window_passes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "notification_state.json"
            ok, remaining = mod.should_send(
                state_path,
                "event.warn",
                level=mod.LEVEL_WARN,
                now_ts=1000.0,
            )
            self.assertTrue(ok)
            self.assertEqual(remaining, 0)

            mod.mark_sent(state_path, "event.warn", now_ts=1000.0)

            ok2, remaining2 = mod.should_send(
                state_path,
                "event.warn",
                level=mod.LEVEL_WARN,
                now_ts=1001.0,
            )
            self.assertFalse(ok2)
            self.assertGreaterEqual(remaining2, 1)

            ok3, remaining3 = mod.should_send(
                state_path,
                "event.warn",
                level=mod.LEVEL_WARN,
                now_ts=1000.0 + mod.LEVEL_COOLDOWN_SEC[mod.LEVEL_WARN] + 1,
            )
            self.assertTrue(ok3)
            self.assertEqual(remaining3, 0)


if __name__ == "__main__":
    unittest.main()
