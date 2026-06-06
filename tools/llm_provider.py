#!/usr/bin/env python3
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


OPENAI_BASE_URL_DEFAULT = "https://api.openai.com/v1"
OLLAMA_BASE_URL_DEFAULT = "http://127.0.0.1:11434"


def normalize_openai_base_url(base_url: str) -> str:
    s = str(base_url or "").strip()
    if not s:
        return OPENAI_BASE_URL_DEFAULT
    return s.rstrip("/")


def normalize_ollama_base_url(base_url: str) -> str:
    s = str(base_url or "").strip()
    if not s:
        return OLLAMA_BASE_URL_DEFAULT
    return s.rstrip("/")


def extract_openai_response_text(data: Dict[str, Any]) -> str:
    text = str(data.get("output_text", "") or "").strip()
    if text:
        return text

    # Responses API returns output[].content[] blocks. Keep this parser tolerant
    # so minor response-shape changes do not break notifier fallbacks.
    parts: list[str] = []
    output = data.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_text = block.get("text")
                if isinstance(block_text, str) and block_text.strip():
                    parts.append(block_text.strip())
                    continue
                if isinstance(block_text, dict):
                    value = block_text.get("value")
                    if isinstance(value, str) and value.strip():
                        parts.append(value.strip())
    if parts:
        return "\n".join(parts).strip()

    # Compatibility fallback for chat-completions-like gateways.
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()
            choice_text = first.get("text")
            if isinstance(choice_text, str) and choice_text.strip():
                return choice_text.strip()
    return ""


def extract_ollama_response_text(data: Dict[str, Any]) -> str:
    text = str(data.get("response", "") or "").strip()
    if text:
        return text
    message = data.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""


def list_ollama_models(*, base_url: str, timeout_sec: int = 5) -> list[str]:
    req = urllib.request.Request(
        url=f"{normalize_ollama_base_url(base_url)}/api/tags",
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=float(timeout_sec)) as resp:
        raw = resp.read()
    data = json.loads(raw.decode("utf-8", errors="replace"))
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        return []
    out: list[str] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "") or "").strip()
        if name:
            out.append(name)
    return out


def run_ollama_generate_summary(
    *,
    base_url: str,
    model: str,
    prompt: str,
    system: str = "",
    timeout_sec: int,
    max_chars: int,
    options: Optional[Dict[str, Any]] = None,
    format_json: bool = False,
) -> str:
    chosen_model = str(model or "").strip()
    if not chosen_model:
        raise ValueError("ollama model is empty")
    payload: Dict[str, Any] = {
        "model": chosen_model,
        "prompt": str(prompt or ""),
        "stream": False,
    }
    if system:
        payload["system"] = str(system)
    if options:
        payload["options"] = dict(options)
    if bool(format_json):
        payload["format"] = "json"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url=f"{normalize_ollama_base_url(base_url)}/api/generate",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=float(timeout_sec)) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"ollama http={e.code}{suffix}") from e

    data = json.loads(raw.decode("utf-8", errors="replace"))
    if not isinstance(data, dict):
        raise ValueError("invalid response object from ollama")
    text = extract_ollama_response_text(data)
    if not text:
        raise ValueError("empty response from ollama")
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars].rstrip() + "..."
    return text


def run_openai_responses_summary(
    *,
    api_key: str,
    base_url: str,
    model: str,
    prompt: str,
    instructions: str = "",
    timeout_sec: int,
    max_chars: int,
    max_output_tokens: int = 320,
) -> str:
    key = str(api_key or "").strip()
    if not key:
        raise ValueError("openai api key is empty")
    chosen_model = str(model or "").strip()
    if not chosen_model:
        raise ValueError("openai model is empty")

    payload: Dict[str, Any] = {
        "model": chosen_model,
        "input": str(prompt or ""),
    }
    if instructions:
        payload["instructions"] = str(instructions)
    if int(max_output_tokens or 0) > 0:
        payload["max_output_tokens"] = int(max_output_tokens)

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url=f"{normalize_openai_base_url(base_url)}/responses",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=float(timeout_sec)) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"openai http={e.code}{suffix}") from e

    data = json.loads(raw.decode("utf-8", errors="replace"))
    if not isinstance(data, dict):
        raise ValueError("invalid response object from openai")
    text = extract_openai_response_text(data)
    if not text:
        raise ValueError("empty response from openai")
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars].rstrip() + "..."
    return text
