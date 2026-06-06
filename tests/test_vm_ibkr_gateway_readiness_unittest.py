import unittest

from tools import vm_ibkr_gateway_readiness as mod


class VmIbkrGatewayReadinessTest(unittest.TestCase):
    def test_parse_remote_lines_extracts_capabilities(self) -> None:
        text = "\n".join(
            [
                "section=commands",
                "cmd_java=1:/usr/bin/java",
                "cmd_Xvfb=1:/usr/bin/Xvfb",
                "cmd_x11vnc=0",
                "section=ibgateway_files",
                "path=/home/ubuntu/Jts",
                "section=process",
                "proc=ubuntu 1 0.0 ibgateway",
                "section=ports",
                "listen=LISTEN 0 50 127.0.0.1:7497 0.0.0.0:*",
            ]
        )
        parsed = mod._parse_remote_lines(text)
        self.assertTrue(parsed["commands"]["java"]["present"])
        self.assertEqual(parsed["ibgateway_paths"], ["/home/ubuntu/Jts"])
        self.assertTrue(parsed["process_lines"])
        self.assertTrue(parsed["listen_lines"])

    def test_build_readiness_ready_smoke(self) -> None:
        parsed = {
            "commands": {
                "java": {"present": True},
                "Xvfb": {"present": True},
                "x11vnc": {"present": True},
                "openbox": {"present": True},
            },
            "ibgateway_paths": ["/home/ubuntu/Jts"],
            "process_lines": ["ubuntu 1 0.0 ibgateway"],
            "listen_lines": ["LISTEN 0 50 127.0.0.1:7497 0.0.0.0:*"],
        }
        readiness = mod.build_readiness(parsed, ssh_ok=True)
        self.assertEqual(readiness["status"], "READY_SMOKE")
        self.assertTrue(readiness["capabilities"]["port_7497_listening"])

    def test_build_readiness_blocks_without_headless_display(self) -> None:
        parsed = {
            "commands": {"java": {"present": True}},
            "ibgateway_paths": [],
            "process_lines": [],
            "listen_lines": [],
        }
        readiness = mod.build_readiness(parsed, ssh_ok=True)
        self.assertEqual(readiness["status"], "BLOCKED")
        self.assertIn("headless_display_missing", readiness["blockers"])

    def test_report_without_host_is_safe_plan(self) -> None:
        report = mod.build_report("", "ubuntu", "", 1.0)
        self.assertEqual(report["mode"], "local_plan")
        self.assertEqual(report["readiness"]["status"], "LOCAL_PLAN")
        self.assertFalse(report["safety"]["starts_services"])
        self.assertFalse(report["safety"]["opens_public_ports"])

    def test_ssh_command_wraps_remote_script_as_single_bash_lc_argument(self) -> None:
        cmd = mod._ssh_command("161.33.26.35", "ubuntu", "/tmp/key", 8.0)
        self.assertEqual(cmd[-2], "ubuntu@161.33.26.35")
        self.assertTrue(cmd[-1].startswith("bash -lc "))
        self.assertIn("section=system", cmd[-1])

    def test_render_markdown_mentions_tunnel_smoke(self) -> None:
        report = {
            "generated_at_jst": "2026-05-06 21:00:00",
            "host": "vm",
            "safety": mod._safety_block(),
            "readiness": {
                "status": "READY_SMOKE",
                "blockers": [],
                "warnings": [],
                "next_steps": [],
                "capabilities": {"java": True},
            },
        }
        md = mod.render_markdown(report)
        self.assertIn("open_vm_ibkr_tunnel.sh", md)
        self.assertIn("--port 17497", md)


if __name__ == "__main__":
    unittest.main()
