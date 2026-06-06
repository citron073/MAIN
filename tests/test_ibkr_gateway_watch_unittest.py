import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
import tempfile

from tools import ibkr_gateway_watch as mod


class IbkrGatewayWatchTest(unittest.TestCase):
    def test_decision_ok_does_not_notify_when_already_ok(self) -> None:
        report = {
            "ibkr_log_status": {
                "connected": True,
                "needs_smoke": False,
                "stale": False,
                "tws_port_status": {"open": True},
                "runtime_status": {"running": True, "runtime": "IB Gateway"},
            }
        }
        state = {"last_issue_key": "OK", "last_status_ok": True}
        decision = mod.build_watch_decision(
            report,
            state,
            now=datetime(2026, 5, 6, 9, 0, 0),
            cooldown_hours=6,
        )
        self.assertTrue(decision["ok"])
        self.assertEqual(decision["event"], "steady_ok")
        self.assertFalse(decision["should_notify"])

    def test_decision_recovery_notifies_once(self) -> None:
        report = {
            "ibkr_log_status": {
                "connected": True,
                "needs_smoke": False,
                "stale": False,
                "tws_port_status": {"open": True},
                "runtime_status": {"running": True, "runtime": "IB Gateway"},
            }
        }
        state = {"last_issue_key": "port_closed", "last_status_ok": False}
        decision = mod.build_watch_decision(
            report,
            state,
            now=datetime(2026, 5, 6, 9, 0, 0),
            cooldown_hours=6,
        )
        self.assertTrue(decision["ok"])
        self.assertEqual(decision["event"], "recovered")
        self.assertTrue(decision["should_notify"])

    def test_decision_issue_notifies_on_new_issue(self) -> None:
        report = {
            "ibkr_log_status": {
                "connected": False,
                "needs_smoke": True,
                "stale": False,
                "tws_port_status": {"open": False, "next_action": "port closed"},
                "runtime_status": {"running": True, "runtime": "IB Gateway"},
            }
        }
        state = {"last_issue_key": "OK", "last_status_ok": True}
        decision = mod.build_watch_decision(
            report,
            state,
            now=datetime(2026, 5, 6, 9, 0, 0),
            cooldown_hours=6,
        )
        self.assertFalse(decision["ok"])
        self.assertEqual(decision["issue_key"], "port_closed")
        self.assertTrue(decision["should_notify"])
        self.assertIn("port closed", decision["reason"])

    def test_decision_issue_suppressed_during_cooldown(self) -> None:
        now = datetime(2026, 5, 6, 9, 0, 0)
        report = {
            "ibkr_log_status": {
                "connected": False,
                "needs_smoke": True,
                "stale": False,
                "tws_port_status": {"open": False, "next_action": "port closed"},
                "runtime_status": {"running": True, "runtime": "IB Gateway"},
            }
        }
        state = {
            "last_issue_key": "port_closed",
            "last_sent_at_jst": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
        }
        decision = mod.build_watch_decision(report, state, now=now, cooldown_hours=6)
        self.assertFalse(decision["ok"])
        self.assertFalse(decision["should_notify"])

    def test_build_message_never_suggests_ordering(self) -> None:
        title, body, tags = mod.build_message(
            {"ok": False, "reason": "port closed", "summary": {"port_open": False}},
            {"day8": "20260506"},
        )
        self.assertIn("Check", title)
        self.assertIn("orders: not touched", body)
        self.assertEqual(tags, "warning")

    def test_vm_mode_marks_port_closed_even_if_service_is_active(self) -> None:
        proc = mock.Mock(stdout="bot=active\nport=closed\n", returncode=0)
        with tempfile.TemporaryDirectory() as td:
            sync_dir = Path(td) / ".local_llm" / "ibkr"
            sync_dir.mkdir(parents=True, exist_ok=True)
            (sync_dir / "ibkr_state.json").write_text("{}", encoding="utf-8")
            with mock.patch.object(mod, "ROOT", Path(td)):
                with mock.patch.object(mod.daily_ops_check, "IBKR_TWS_PORT", 7496):
                    with mock.patch.object(mod.subprocess, "run", return_value=proc):
                        decision, title, body, tags = mod._vm_mode_check(
                            "161.33.26.35",
                            "ubuntu",
                            "/tmp/key",
                            {"last_issue_key": "OK"},
                            datetime(2026, 5, 8, 9, 0, 0),
                            6.0,
                        )
        self.assertFalse(decision["ok"])
        self.assertEqual(decision["issue_key"], "port_closed")
        self.assertEqual(decision["port_status"], "closed")
        self.assertIn("7496", decision["reason"])
        self.assertIn("7496", body)
        self.assertEqual(tags, "warning")
        self.assertIn("WARN", title)

    def test_vm_mode_uses_configured_api_port(self) -> None:
        proc = mock.Mock(stdout="bot=active\nport=open\n", returncode=0)
        with tempfile.TemporaryDirectory() as td:
            sync_dir = Path(td) / ".local_llm" / "ibkr"
            sync_dir.mkdir(parents=True, exist_ok=True)
            (sync_dir / "ibkr_state.json").write_text("{}", encoding="utf-8")
            with mock.patch.object(mod, "ROOT", Path(td)):
                with mock.patch.object(mod.daily_ops_check, "IBKR_TWS_PORT", 7496):
                    with mock.patch.object(mod.subprocess, "run", return_value=proc) as run_mock:
                        mod._vm_mode_check(
                            "161.33.26.35",
                            "ubuntu",
                            "/tmp/key",
                            {"last_issue_key": "OK"},
                            datetime(2026, 5, 8, 9, 0, 0),
                            6.0,
                        )
        remote_cmd = run_mock.call_args.args[0][-1]
        self.assertIn(":7496 ", remote_cmd)
        self.assertNotIn(":7497 ", remote_cmd)

    def test_vm_mode_port_closed_legacy_paper_default(self) -> None:
        proc = mock.Mock(stdout="bot=active\nport=closed\n", returncode=0)
        with tempfile.TemporaryDirectory() as td:
            sync_dir = Path(td) / ".local_llm" / "ibkr"
            sync_dir.mkdir(parents=True, exist_ok=True)
            (sync_dir / "ibkr_state.json").write_text("{}", encoding="utf-8")
            with mock.patch.object(mod, "ROOT", Path(td)):
                with mock.patch.object(mod.daily_ops_check, "IBKR_TWS_PORT", 7497):
                    with mock.patch.object(mod.subprocess, "run", return_value=proc):
                        decision, title, body, tags = mod._vm_mode_check(
                            "161.33.26.35",
                            "ubuntu",
                            "/tmp/key",
                            {"last_issue_key": "OK"},
                            datetime(2026, 5, 8, 9, 0, 0),
                            6.0,
                        )
        self.assertFalse(decision["ok"])
        self.assertEqual(decision["issue_key"], "port_closed")
        self.assertEqual(decision["port_status"], "closed")
        self.assertIn("7497", decision["reason"])
        self.assertIn("7497", body)
        self.assertEqual(tags, "warning")
        self.assertIn("WARN", title)

    def test_vm_mode_ok_requires_service_and_port(self) -> None:
        proc = mock.Mock(stdout="bot=active\nport=open\n", returncode=0)
        with tempfile.TemporaryDirectory() as td:
            sync_dir = Path(td) / ".local_llm" / "ibkr"
            sync_dir.mkdir(parents=True, exist_ok=True)
            (sync_dir / "ibkr_state.json").write_text('{"daily_trade_count":2}', encoding="utf-8")
            with mock.patch.object(mod, "ROOT", Path(td)):
                with mock.patch.object(mod.subprocess, "run", return_value=proc):
                    decision, title, body, tags = mod._vm_mode_check(
                        "161.33.26.35",
                        "ubuntu",
                        "/tmp/key",
                        {"last_issue_key": "port_closed"},
                        datetime(2026, 5, 8, 9, 0, 0),
                        6.0,
                    )
        self.assertTrue(decision["ok"])
        self.assertEqual(decision["issue_key"], "OK")
        self.assertEqual(decision["port_status"], "open")
        self.assertIn("active on VM", body)
        self.assertEqual(tags, "white_check_mark")


if __name__ == "__main__":
    unittest.main()
