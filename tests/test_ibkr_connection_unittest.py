import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import test_ibkr_connection as mod


class TestIbkrConnectionDiagnostics(unittest.TestCase):
    def test_probe_tcp_port_open(self) -> None:
        fake_socket = mock.MagicMock()
        fake_socket.__enter__.return_value = fake_socket
        with mock.patch.object(mod.socket, "create_connection", return_value=fake_socket):
            status = mod._probe_tcp_port("127.0.0.1", 7497)
        self.assertTrue(status["open"])

    def test_probe_tcp_port_closed(self) -> None:
        with mock.patch.object(mod.socket, "create_connection", side_effect=ConnectionRefusedError("no")):
            status = mod._probe_tcp_port("127.0.0.1", 7497)
        self.assertFalse(status["open"])
        self.assertIn("ConnectionRefusedError", status["error"])

    def test_timeout_diagnosis_mentions_api_response(self) -> None:
        msg = mod._diagnose_connect_error(TimeoutError("handshake timed out"), "127.0.0.1", 7497)
        self.assertIn("IBKR API応答", msg)

    def test_failure_log_uses_error_filename(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = mod._write_failure_log({"connected": False}, Path(td))
            self.assertIn("ibkr_connection_error_", path.name)
            self.assertTrue(path.exists())
            self.assertTrue((Path(td) / "ibkr_connection_error_latest.json").exists())

    def test_success_log_writes_latest_alias(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = mod._write_success_log({"connected": True}, Path(td))
            self.assertIn("ibkr_connection_", path.name)
            self.assertTrue(path.exists())
            self.assertTrue((Path(td) / "ibkr_connection_latest.json").exists())

    def test_checklist_contains_client_id_and_readonly(self) -> None:
        checklist = mod._ibkr_timeout_checklist("127.0.0.1", 7497, 17)
        joined = "\n".join(checklist)
        self.assertIn("Read-Only", joined)
        self.assertIn("clientId=17", joined)
        self.assertIn("--client-id 17", joined)

    def test_parse_client_id_candidates_dedupes_primary_first(self) -> None:
        self.assertEqual(mod._parse_client_id_candidates("17,101,17,bad", 1), [1, 17, 101])

    def test_diagnose_client_ids_reports_first_ok(self) -> None:
        adapters = []

        class FakeAdapter:
            def __init__(self, **kwargs):
                self.client_id = kwargs["client_id"]
                adapters.append(self)

            def connect(self):
                if self.client_id == 17:
                    return True
                raise TimeoutError("nope")

            def disconnect(self):
                pass

        with mock.patch.object(mod, "IBKRAdapter", FakeAdapter):
            result = mod._diagnose_client_ids("127.0.0.1", 7497, [1, 17, 101], "delayed", 0.1)
        self.assertEqual(result["first_ok_client_id"], 17)
        self.assertIn("IBKR_CLIENT_ID=17", result["recommendation"])

    def test_diagnose_client_ids_can_skip_primary(self) -> None:
        seen = []

        class FakeAdapter:
            def __init__(self, **kwargs):
                seen.append(kwargs["client_id"])

            def connect(self):
                raise TimeoutError("nope")

            def disconnect(self):
                pass

        with mock.patch.object(mod, "IBKRAdapter", FakeAdapter):
            result = mod._diagnose_client_ids("127.0.0.1", 7497, [1, 17, 101], "delayed", 0.1, skip_client_id=1)
        self.assertEqual(seen, [17, 101])
        self.assertIsNone(result["first_ok_client_id"])


if __name__ == "__main__":
    unittest.main()
