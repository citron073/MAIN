from __future__ import annotations

import unittest
from unittest.mock import patch

from tools.print_widget_tailscale_info import _parse_scutil_status_output, build_candidate_urls


SCUTIL_CONNECTED = """Connected
Extended Status <dictionary> {
  ConnectionStatistics : <dictionary> {
    ConnectCount : 1
    ConnectedCount : 1
  }
  DNSSearchDomains : <array> {
    0 : tail0e49bc.ts.net.
  }
  IPv4 : <dictionary> {
    Addresses : <array> {
      0 : 100.71.123.5
    }
  }
  IPv6 : <dictionary> {
    Addresses : <array> {
      0 : fd7a:115c:a1e0::6001:7bb1
    }
  }
  Status : 2
}
"""


class PrintWidgetTailscaleInfoTest(unittest.TestCase):
    def test_parse_scutil_status_output_extracts_ips_and_dns(self) -> None:
        parsed = _parse_scutil_status_output(SCUTIL_CONNECTED)

        self.assertTrue(parsed["connected"])
        self.assertEqual(parsed["dns_name"], "tail0e49bc.ts.net")
        self.assertEqual(parsed["tailscale_ips"][0], "100.71.123.5")
        self.assertIn("fd7a:115c:a1e0::6001:7bb1", parsed["tailscale_ips"])

    def test_build_candidate_urls_falls_back_to_scutil(self) -> None:
        def fake_run(cmd: list[str]) -> tuple[int, str, str]:
            if cmd == ["scutil", "--nc", "status", "Tailscale 2"]:
                return 0, SCUTIL_CONNECTED, ""
            return 1, "", "not found"

        with patch("tools.print_widget_tailscale_info._tailscale_installed", return_value=False):
            with patch("tools.print_widget_tailscale_info._run", side_effect=fake_run):
                info = build_candidate_urls(port=8787)

        self.assertTrue(info["ok"])
        self.assertEqual(info["service_name"], "Tailscale 2")
        self.assertIn("http://tail0e49bc.ts.net:8787", info["base_urls"])
        self.assertIn("http://100.71.123.5:8787", info["base_urls"])
        self.assertIn("http://tail0e49bc.ts.net:8787/widget-react/index.html", info["widget_react_urls"])
        self.assertIn("http://tail0e49bc.ts.net:8787/widget-react/index.html?scene=overview&native=1", info["widget_react_scene_urls"]["overview"])
        self.assertIn("http://tail0e49bc.ts.net:8787/widget-react/index.html?scene=reflection&native=1", info["widget_react_scene_urls"]["reflection"])
        self.assertIn("http://tail0e49bc.ts.net:8787/widget-react/index.html?scene=home", info["widget_react_scene_urls"]["home"])
        self.assertIn("http://tail0e49bc.ts.net:8787/widget-react/index.html?scene=lock", info["widget_react_scene_urls"]["lock"])
        self.assertIn("http://tail0e49bc.ts.net:8787/widget-react/index.html?scene=standby", info["widget_react_scene_urls"]["standby"])
        self.assertIn("http://tail0e49bc.ts.net:8787/widget-home", info["widget_home_urls"])
        self.assertIn("http://tail0e49bc.ts.net:8787/widget-app", info["widget_app_urls"])
        self.assertIn("http://100.71.123.5:8787/unified_dashboard.html", info["dashboard_urls"])


if __name__ == "__main__":
    unittest.main()
