import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from tools import daily_ops_check as mod


class DailyOpsCheckTest(unittest.TestCase):
    def test_tws_port_status_reports_open(self) -> None:
        fake_socket = mock.MagicMock()
        fake_socket.__enter__.return_value = fake_socket
        with mock.patch.object(mod.socket, "create_connection", return_value=fake_socket):
            status = mod.build_tws_port_status()
        self.assertTrue(status["open"])
        self.assertEqual(status["next_action"], "OK")

    def test_tws_port_status_reports_closed(self) -> None:
        with mock.patch.object(mod.socket, "create_connection", side_effect=OSError("closed")):
            status = mod.build_tws_port_status()
        self.assertFalse(status["open"])
        self.assertIn(str(mod.IBKR_TWS_PORT), status["next_action"])

    def test_ibkr_runtime_status_detects_gateway(self) -> None:
        proc = mock.Mock(stdout="user 1 0.0 /Applications/IBGateway/ibgateway", stderr="")
        with mock.patch.object(mod.subprocess, "run", return_value=proc):
            status = mod.build_ibkr_runtime_status()
        self.assertTrue(status["running"])
        self.assertEqual(status["runtime"], "IB Gateway")
        self.assertIn("Gateway", status["preferred_runtime"])

    def test_ibkr_runtime_status_reports_not_running(self) -> None:
        proc = mock.Mock(stdout="user 1 0.0 zsh", stderr="")
        with mock.patch.object(mod.subprocess, "run", return_value=proc):
            status = mod.build_ibkr_runtime_status()
        self.assertFalse(status["running"])
        self.assertIn("IB Gateway", status["next_action"])

    def test_ibkr_log_status_marks_missing_today_as_smoke_needed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(mod, "build_tws_port_status", return_value={"open": False, "next_action": "port closed"}), \
                mock.patch.object(mod, "build_ibkr_runtime_status", return_value={"running": True, "next_action": "OK", "setup_checklist": []}):
                    status = mod.build_ibkr_log_status(Path(td), "20260506")
        self.assertTrue(status["needs_smoke"])
        self.assertEqual(status["latest_available"], False)
        self.assertEqual(status["next_action"], "port closed")
        self.assertIn("--fx USDJPY", status["read_only_smoke_command"])

    def test_ibkr_log_status_surfaces_latest_error_diagnosis(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            day8 = "20260506"
            (out_dir / f"ibkr_connection_error_{day8}.json").write_text(
                '{"stage":"connect","diagnosis":"API timeout","detail":"TimeoutError","checklist":["a","b"],"client_id_diagnostics":{"first_ok_client_id":17,"recommendation":"use 17"}}\n',
                encoding="utf-8",
            )
            with mock.patch.object(mod, "build_tws_port_status", return_value={"open": True, "next_action": "OK"}), \
                mock.patch.object(mod, "build_ibkr_runtime_status", return_value={"running": True, "next_action": "OK", "setup_checklist": []}):
                status = mod.build_ibkr_log_status(out_dir, day8)
        self.assertTrue(status["needs_smoke"])
        self.assertEqual(status["latest_error_diagnosis"], "API timeout")
        self.assertTrue(status["active_error_available"])
        self.assertEqual(status["active_error_diagnosis"], "API timeout")
        self.assertEqual(status["next_action"], "API timeout")
        self.assertEqual(status["latest_error_checklist"], ["a", "b"])
        self.assertEqual(status["client_id_diagnostics"]["first_ok_client_id"], 17)

    def test_ibkr_log_status_does_not_treat_error_log_as_success_log(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            (out_dir / "ibkr_connection_error_20260506.json").write_text(
                '{"generated_at_jst":"2026-05-06 08:00:00","connected":false,"diagnosis":"API timeout"}\n',
                encoding="utf-8",
            )
            with mock.patch.object(mod, "build_tws_port_status", return_value={"open": True, "next_action": "OK"}), \
                mock.patch.object(mod, "build_ibkr_runtime_status", return_value={"running": True, "next_action": "OK", "setup_checklist": []}):
                status = mod.build_ibkr_log_status(out_dir, "20260506")
        self.assertFalse(status["latest_available"])
        self.assertEqual(status["latest_path"], "")
        self.assertTrue(status["latest_error_available"])

    def test_ibkr_log_status_is_ok_for_fresh_connected_today(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            day8 = "20260506"
            now = datetime.utcnow()
            generated = now.strftime("%Y-%m-%d %H:%M:%S")
            (out_dir / f"ibkr_connection_{day8}.json").write_text(
                '{"generated_at_jst":"%s","connected":true,"positions":[]}\n' % generated,
                encoding="utf-8",
            )
            with mock.patch.object(mod, "_now_jst_naive", return_value=now):
                with mock.patch.object(mod, "build_tws_port_status", return_value={"open": True, "next_action": "OK"}), \
                    mock.patch.object(mod, "build_ibkr_runtime_status", return_value={"running": True, "next_action": "OK", "setup_checklist": []}):
                    status = mod.build_ibkr_log_status(out_dir, day8)
        self.assertFalse(status["needs_smoke"])
        self.assertEqual(status["next_action"], "OK")

    def test_vm_ibkr_readiness_status_reports_ready_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            day8 = "20260506"
            now = datetime.utcnow()
            (out_dir / f"vm_ibkr_gateway_readiness_{day8}.json").write_text(
                json.dumps(
                    {
                        "generated_at_jst": now.strftime("%Y-%m-%d %H:%M:%S"),
                        "readiness": {
                            "status": "READY_SMOKE",
                            "capabilities": {
                                "ibgateway_running": True,
                                "port_7497_listening": True,
                            },
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(mod, "_now_jst_naive", return_value=now):
                status = mod.build_vm_ibkr_readiness_status(out_dir, day8)
        self.assertTrue(status["ok"])
        self.assertEqual(status["status"], "READY_SMOKE")
        self.assertEqual(status["next_action"], "OK")

    def test_ibkr_log_status_prefers_vm_tunnel_success(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            day8 = "20260506"
            now = datetime.utcnow()
            generated = now.strftime("%Y-%m-%d %H:%M:%S")
            (out_dir / f"ibkr_connection_{day8}.json").write_text(
                json.dumps(
                    {
                        "generated_at_jst": generated,
                        "connected": True,
                        "host": "127.0.0.1",
                        "port": 17497,
                        "positions": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (out_dir / f"vm_ibkr_gateway_readiness_{day8}.json").write_text(
                json.dumps(
                    {
                        "generated_at_jst": generated,
                        "readiness": {
                            "status": "READY_SMOKE",
                            "capabilities": {
                                "ibgateway_running": True,
                                "port_7497_listening": True,
                            },
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            def fake_port(host: str = "127.0.0.1", port: int = 7497, timeout_sec: float = 0.5):
                open_ = port == 17497
                return {
                    "host": host,
                    "port": port,
                    "open": open_,
                    "error": "",
                    "check": f"{host}:{port}",
                    "next_action": "OK" if open_ else "closed",
                }

            with mock.patch.object(mod, "_now_jst_naive", return_value=now):
                with mock.patch.object(mod, "build_tws_port_status", side_effect=fake_port), \
                    mock.patch.object(mod, "build_ibkr_runtime_status", return_value={"running": False, "next_action": "local closed", "setup_checklist": []}):
                    status = mod.build_ibkr_log_status(out_dir, day8)

        self.assertEqual(status["api_mode"], "vm_tunnel")
        self.assertFalse(status["needs_smoke"])
        self.assertEqual(status["next_action"], "OK")
        self.assertTrue(status["effective_port_status"]["open"])
        self.assertTrue(status["effective_runtime_status"]["running"])
        self.assertIn("--port 17497", status["read_only_smoke_command"])

    def test_ibkr_log_status_suppresses_local_dependency_error_when_vm_is_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            day8 = "20260506"
            now = datetime.utcnow()
            generated = now.strftime("%Y-%m-%d %H:%M:%S")
            (out_dir / f"ibkr_connection_error_{day8}.json").write_text(
                json.dumps(
                    {
                        "stage": "dependency",
                        "diagnosis": "ib_insync が未インストールです。python3 -m pip install ib_insync を実行してください。",
                        "detail": "IBKRDependencyError: ib_insync not installed",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (out_dir / f"vm_ibkr_gateway_readiness_{day8}.json").write_text(
                json.dumps(
                    {
                        "generated_at_jst": generated,
                        "readiness": {
                            "status": "READY_SMOKE",
                            "capabilities": {
                                "ibgateway_running": True,
                                "port_7497_listening": True,
                            },
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(mod, "_now_jst_naive", return_value=now):
                with mock.patch.object(mod, "build_tws_port_status", return_value={"open": False, "next_action": "closed"}), \
                    mock.patch.object(mod, "build_ibkr_runtime_status", return_value={"running": False, "next_action": "local closed", "setup_checklist": []}):
                    status = mod.build_ibkr_log_status(out_dir, day8)
        self.assertFalse(status["needs_smoke"])
        self.assertFalse(status["active_error_available"])
        self.assertEqual(status["next_action"], "OK")
        self.assertEqual(status["effective_port_status"]["check"], f"vm:127.0.0.1:{mod.IBKR_TWS_PORT}")
        self.assertEqual(status["read_only_smoke_command"], mod.IBKR_VM_READINESS_COMMAND)

    def test_ibkr_log_status_prefers_vm_readiness_refresh_over_local_dependency_error_when_stale(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            day8 = "20260506"
            (out_dir / f"ibkr_connection_error_{day8}.json").write_text(
                json.dumps(
                    {
                        "stage": "dependency",
                        "diagnosis": "ib_insync が未インストールです。python3 -m pip install ib_insync を実行してください。",
                        "detail": "IBKRDependencyError: ib_insync not installed",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (out_dir / f"vm_ibkr_gateway_readiness_{day8}.json").write_text(
                json.dumps(
                    {
                        "generated_at_jst": "2026-05-04 09:00:00",
                        "readiness": {
                            "status": "READY_SMOKE",
                            "capabilities": {
                                "ibgateway_running": True,
                                "port_7497_listening": True,
                            },
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(mod, "_now_jst_naive", return_value=datetime(2026, 5, 6, 9, 30, 0)):
                with mock.patch.object(mod, "build_tws_port_status", return_value={"open": False, "next_action": "closed"}), \
                    mock.patch.object(mod, "build_ibkr_runtime_status", return_value={"running": False, "next_action": "local closed", "setup_checklist": []}):
                    status = mod.build_ibkr_log_status(out_dir, day8)
        self.assertTrue(status["needs_smoke"])
        self.assertFalse(status["active_error_available"])
        self.assertEqual(status["next_action"], "VM IB Gateway readinessを再実行")

    def test_ibkr_log_status_keeps_old_error_inactive_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            day8 = "20260506"
            now = datetime.utcnow()
            generated = now.strftime("%Y-%m-%d %H:%M:%S")
            (out_dir / f"ibkr_connection_{day8}.json").write_text(
                '{"generated_at_jst":"%s","connected":true,"positions":[]}\n' % generated,
                encoding="utf-8",
            )
            (out_dir / f"ibkr_connection_error_{day8}.json").write_text(
                '{"stage":"connect","diagnosis":"old failure","detail":"ConnectionRefusedError","checklist":["x"]}\n',
                encoding="utf-8",
            )
            with mock.patch.object(mod, "_now_jst_naive", return_value=now):
                with mock.patch.object(mod, "build_tws_port_status", return_value={"open": True, "next_action": "OK"}), \
                    mock.patch.object(mod, "build_ibkr_runtime_status", return_value={"running": True, "next_action": "OK", "setup_checklist": []}):
                    status = mod.build_ibkr_log_status(out_dir, day8)
        self.assertFalse(status["needs_smoke"])
        self.assertTrue(status["latest_error_available"])
        self.assertFalse(status["active_error_available"])
        self.assertEqual(status["active_error_diagnosis"], "")

    def test_version_consistency_status_wraps_success(self) -> None:
        expected = {"ok": True, "expected": {"bot_logic": "v", "feature_schema": "s"}, "items": []}
        with mock.patch.object(mod.version_consistency_check, "run_version_consistency_check", return_value=expected):
            self.assertEqual(mod.build_version_consistency_status(), expected)

    def test_version_consistency_status_wraps_exception(self) -> None:
        with mock.patch.object(mod.version_consistency_check, "run_version_consistency_check", side_effect=RuntimeError("boom")):
            result = mod.build_version_consistency_status()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_count"], 1)
        self.assertIn("boom", result["error"])

    def test_ibkr_import_audit_status_wraps_success(self) -> None:
        expected = {"ok": True, "next_action": "OK"}
        with mock.patch.object(mod.ibkr_import_audit, "build_audit", return_value=expected):
            self.assertEqual(mod.build_ibkr_import_audit_status(), expected)

    def test_ibkr_import_audit_status_wraps_exception(self) -> None:
        with mock.patch.object(mod.ibkr_import_audit, "build_audit", side_effect=RuntimeError("boom")):
            result = mod.build_ibkr_import_audit_status()
        self.assertFalse(result["ok"])
        self.assertIn("boom", result["next_action"])

    def test_ibkr_watch_state_status_reports_ok(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ibkr_gateway_watch_state.json"
            now = datetime.utcnow()
            path.write_text(
                '{"last_issue_key":"OK","last_status_ok":true,"last_checked_at_jst":"%s","last_reason":"OK"}\n'
                % now.strftime("%Y-%m-%d %H:%M:%S"),
                encoding="utf-8",
            )
            with mock.patch.object(mod, "_now_jst_naive", return_value=now):
                status = mod.build_ibkr_watch_state_status(path)
        self.assertTrue(status["available"])
        self.assertEqual(status["label"], "OK")
        self.assertFalse(status["stale"])

    def test_ibkr_watch_state_status_marks_stale(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ibkr_gateway_watch_state.json"
            path.write_text(
                '{"last_issue_key":"OK","last_status_ok":true,"last_checked_at_jst":"2026-05-06 08:00:00","last_reason":"OK"}\n',
                encoding="utf-8",
            )
            with mock.patch.object(mod, "_now_jst_naive", return_value=datetime(2026, 5, 6, 8, 30, 0)):
                status = mod.build_ibkr_watch_state_status(path)
        self.assertEqual(status["label"], "古い")
        self.assertTrue(status["stale"])

    def test_run_daily_ops_check_writes_version_consistency(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            latest_ibkr = out_dir / "ibkr_connection_20260505.json"
            latest_ibkr.write_text('{"generated_at_jst":"2026-05-05 09:00:00","connected":true}\n', encoding="utf-8")
            latest_ibkr_error = out_dir / "ibkr_connection_error_20260505.json"
            latest_ibkr_error.write_text('{"stage":"connect","diagnosis":"old error"}\n', encoding="utf-8")
            dashboard_report = {
                "day8": "20260506",
                "checked_at_jst": "2026-05-06 09:00:00",
                "dashboard": {"ok": True, "status_code": 200},
                "rolling_7d": {"score": 100},
            }
            zero_report = {
                "day8": "20260506",
                "row_n": 0,
                "classification": {"category": "market_time_window", "label": "取引時間前"},
            }
            version_report = {
                "ok": True,
                "expected": {"bot_logic": "2026.05.05.3", "feature_schema": "schema-v1"},
                "items": [],
                "error_count": 0,
            }
            import_report = {"ok": True, "next_action": "OK"}
            with mock.patch.object(mod.unified_dashboard_healthcheck, "build_report", return_value=dashboard_report), \
                mock.patch.object(mod.trade_log_zero_day_review, "build_report", return_value=zero_report), \
                mock.patch.object(mod, "build_ibkr_log_status", return_value={"connected": False, "latest_path": str(latest_ibkr), "latest_error_path": str(latest_ibkr_error)}), \
                mock.patch.object(mod, "build_ibkr_watch_state_status", return_value={"label": "OK"}), \
                mock.patch.object(mod, "build_version_consistency_status", return_value=version_report), \
                mock.patch.object(mod, "build_ibkr_import_audit_status", return_value=import_report):
                report = mod.run_daily_ops_check(out_dir, "http://127.0.0.1:8793/", 1.0)

            self.assertEqual(report["version_consistency"], version_report)
            self.assertEqual(report["ibkr_watch_state"]["label"], "OK")
            self.assertEqual(report["ibkr_import_audit"], import_report)
            written = out_dir / "daily_ops_check_20260506.json"
            self.assertTrue(written.exists())
            self.assertIn('"version_consistency"', written.read_text(encoding="utf-8"))
            self.assertTrue((out_dir / "daily_ops_check_latest.json").exists())
            self.assertTrue((out_dir / "unified_dashboard_health_latest.json").exists())
            self.assertTrue((out_dir / "trade_log_zero_day_review_latest.json").exists())
            self.assertTrue((out_dir / "ibkr_connection_latest.json").exists())
            self.assertTrue((out_dir / "ibkr_connection_error_latest.json").exists())


if __name__ == "__main__":
    unittest.main()
