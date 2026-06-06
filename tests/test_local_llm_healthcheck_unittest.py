from __future__ import annotations

import unittest
from unittest.mock import patch

from tools import local_llm_healthcheck as mod


class LocalLlmHealthcheckTest(unittest.TestCase):
    def test_choose_model_prefers_installed_requested_family(self) -> None:
        selected = mod.choose_model(
            "qwen2.5:3b",
            ["qwen2.5:0.5b", "llama3.2:1b"],
            ["llama3.2:1b", "qwen2.5:0.5b"],
        )
        self.assertEqual(selected, "qwen2.5:0.5b")

    @patch("tools.local_llm_healthcheck.list_ollama_models")
    def test_build_healthcheck_ok_when_model_available(self, mock_list) -> None:
        mock_list.return_value = ["qwen2.5:0.5b"]
        result = mod.build_healthcheck(
            base_url="http://127.0.0.1:11434/",
            preferred_model="qwen2.5:1.5b",
            fallback_models=["qwen2.5:0.5b"],
            timeout_sec=1,
        )
        self.assertEqual(result["status"], "OK")
        self.assertTrue(result["reachable"])
        self.assertEqual(result["selected_model"], "qwen2.5:0.5b")
        self.assertEqual(result["isolation"]["vm_impact"], "none")

    @patch("tools.local_llm_healthcheck.list_ollama_models")
    def test_build_healthcheck_warn_when_ollama_unreachable(self, mock_list) -> None:
        mock_list.side_effect = OSError("connection refused")
        result = mod.build_healthcheck(timeout_sec=1)
        self.assertEqual(result["status"], "WARN")
        self.assertFalse(result["reachable"])
        self.assertEqual(result["reason"], "ollama_unreachable")
        self.assertTrue(result["isolation"]["safe_if_unavailable"])


if __name__ == "__main__":
    unittest.main()
