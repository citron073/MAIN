from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from tools.llm_provider import (
    extract_ollama_response_text,
    extract_openai_response_text,
    list_ollama_models,
    normalize_ollama_base_url,
    normalize_openai_base_url,
    run_ollama_generate_summary,
)


class LlmProviderTest(unittest.TestCase):
    def test_extract_openai_response_text_prefers_output_text(self) -> None:
        self.assertEqual(
            extract_openai_response_text({"output_text": "総評: ok"}),
            "総評: ok",
        )

    def test_extract_openai_response_text_reads_responses_output_blocks(self) -> None:
        payload = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "総評: 週次は保留。"},
                        {"type": "output_text", "text": "次アクション: shadowを継続観察。"},
                    ],
                }
            ]
        }
        self.assertEqual(
            extract_openai_response_text(payload),
            "総評: 週次は保留。\n次アクション: shadowを継続観察。",
        )

    def test_extract_openai_response_text_supports_chat_compat_shape(self) -> None:
        payload = {"choices": [{"message": {"content": "総評: compat"}}]}
        self.assertEqual(extract_openai_response_text(payload), "総評: compat")

    def test_normalize_openai_base_url(self) -> None:
        self.assertEqual(normalize_openai_base_url(""), "https://api.openai.com/v1")
        self.assertEqual(normalize_openai_base_url("https://api.example/v1/"), "https://api.example/v1")

    def test_extract_ollama_response_text(self) -> None:
        self.assertEqual(extract_ollama_response_text({"response": "総評: ok"}), "総評: ok")
        self.assertEqual(extract_ollama_response_text({"message": {"content": "chat ok"}}), "chat ok")

    def test_normalize_ollama_base_url(self) -> None:
        self.assertEqual(normalize_ollama_base_url(""), "http://127.0.0.1:11434")
        self.assertEqual(normalize_ollama_base_url("http://127.0.0.1:11434/"), "http://127.0.0.1:11434")

    @patch("tools.llm_provider.urllib.request.urlopen")
    def test_list_ollama_models_reads_tags(self, mock_urlopen: MagicMock) -> None:
        resp = MagicMock()
        resp.read.return_value = b'{"models":[{"name":"qwen2.5:0.5b"},{"name":"llama3.2:1b"}]}'
        mock_urlopen.return_value.__enter__.return_value = resp
        self.assertEqual(
            list_ollama_models(base_url="http://127.0.0.1:11434", timeout_sec=1),
            ["qwen2.5:0.5b", "llama3.2:1b"],
        )

    @patch("tools.llm_provider.urllib.request.urlopen")
    def test_run_ollama_generate_summary_posts_prompt(self, mock_urlopen: MagicMock) -> None:
        resp = MagicMock()
        resp.read.return_value = '{"response":"短い要約"}'.encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = resp
        text = run_ollama_generate_summary(
            base_url="http://127.0.0.1:11434",
            model="qwen2.5:0.5b",
            prompt="summarize",
            timeout_sec=1,
            max_chars=100,
        )
        self.assertEqual(text, "短い要約")


if __name__ == "__main__":
    unittest.main()
