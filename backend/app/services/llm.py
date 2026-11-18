"""Hybrid AI provider layer. Local (Ollama) and optional external LLM providers behind one interface.

Privacy rules enforced here (not only in the UI):
* External (cloud) providers are never called while offline mode is on.
* External providers require explicit enablement AND a privacy acknowledgement.
* Only transcript text + timestamps are sent; video frames only if the provider's `send_frames` flag is on.
* Original media files are never transmitted.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .. import config
from ..security import get_secret

log = logging.getLogger("clipforge.llm")

PROVIDER_KINDS = {
    "ollama": {"label": "Ollama (local)", "local": True, "default_url": "http://127.0.0.1:11434", "needs_key": False, "default_model": "llama3.1:8b"},
    "openai": {"label": "OpenAI", "local": False, "default_url": "https://api.openai.com/v1", "needs_key": True, "default_model": "gpt-4o-mini"},
    "openai_compatible": {"label": "OpenAI-compatible (LM Studio, OpenRouter, Groq...)", "local": False, "default_url": "http://127.0.0.1:1234/v1", "needs_key": False, "default_model": ""},
    "anthropic": {"label": "Anthropic", "local": False, "default_url": "https://api.anthropic.com", "needs_key": True, "default_model": "claude-3-5-haiku-latest"},
    "gemini": {"label": "Google Gemini", "local": False, "default_url": "https://generativelanguage.googleapis.com", "needs_key": True, "default_model": "gemini-1.5-flash"},
}


class ProviderError(RuntimeError):
    pass


@dataclass
class ProviderConfig:
    id: str
    name: str
    kind: str
    base_url: str
    model: str
    enabled: bool
    is_local: bool
    send_frames: bool
    privacy_acknowledged: bool

    @property
    def api_key(self) -> str | None:
        return get_secret(f"provider:{self.id}")


def is_local_url(url: str) -> bool:
    return bool(re.match(r"^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?(/|$)", url or ""))


def check_allowed(p: ProviderConfig) -> None:
    local = p.kind == "ollama" or is_local_url(p.base_url)
    if config.get_settings().get("offline_mode") and not local:
        raise ProviderError("Offline mode is enabled - external AI providers are disabled")
    if not local and not p.privacy_acknowledged:
        raise ProviderError("Review and acknowledge the privacy summary before using this cloud provider")


def _client(timeout: float = 120.0) -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(timeout, connect=10.0))


def list_models(p: ProviderConfig) -> list[str]:
    check_allowed(p)
    url = (p.base_url or PROVIDER_KINDS[p.kind]["default_url"]).rstrip("/")
    with _client(20) as c:
        if p.kind == "ollama":
            r = c.get(f"{url}/api/tags")
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
        if p.kind in ("openai", "openai_compatible"):
            h = {"Authorization": f"Bearer {p.api_key}"} if p.api_key else {}
            r = c.get(f"{url}/models", headers=h)
            r.raise_for_status()
            return sorted(m["id"] for m in r.json().get("data", []))
        if p.kind == "anthropic":
            r = c.get(f"{url}/v1/models", headers={"x-api-key": p.api_key or "", "anthropic-version": "2023-06-01"})
            r.raise_for_status()
            return [m["id"] for m in r.json().get("data", [])]
        if p.kind == "gemini":
            r = c.get(f"{url}/v1beta/models", params={"key": p.api_key or ""})
            r.raise_for_status()
            return [m["name"].split("/")[-1] for m in r.json().get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])]
    return []


def chat_json(p: ProviderConfig, system: str, user: str, images: list[bytes] | None = None, timeout: float = 180.0) -> tuple[dict[str, Any], dict[str, int]]:
    """Send a chat request expecting a JSON object reply. Returns (parsed_json, usage)."""
    check_allowed(p)
    if images and not p.send_frames:
        images = None
    url = (p.base_url or PROVIDER_KINDS[p.kind]["default_url"]).rstrip("/")
    model = p.model or PROVIDER_KINDS[p.kind]["default_model"]
    if not model:
        raise ProviderError("No model selected for this provider")
    usage = {"input_tokens": 0, "output_tokens": 0}
    b64 = [base64.b64encode(i).decode() for i in (images or [])]
    try:
        with _client(timeout) as c:
            if p.kind == "ollama":
                msg: dict[str, Any] = {"role": "user", "content": user}
                if b64:
                    msg["images"] = b64
                r = c.post(f"{url}/api/chat", json={"model": model, "stream": False, "format": "json", "options": {"temperature": 0.2},
                                                   "messages": [{"role": "system", "content": system}, msg]})
                r.raise_for_status()
                d = r.json()
                text = d.get("message", {}).get("content", "")
                usage = {"input_tokens": d.get("prompt_eval_count", 0), "output_tokens": d.get("eval_count", 0)}
            elif p.kind in ("openai", "openai_compatible"):
                content: Any = user
                if b64:
                    content = [{"type": "text", "text": user}] + [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{x}"}} for x in b64]
                h = {"Authorization": f"Bearer {p.api_key}"} if p.api_key else {}
                body = {"model": model, "temperature": 0.2, "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
                        "response_format": {"type": "json_object"}}
                r = c.post(f"{url}/chat/completions", headers=h, json=body)
                if r.status_code == 400 and "response_format" in r.text:
                    body.pop("response_format")
                    r = c.post(f"{url}/chat/completions", headers=h, json=body)
                r.raise_for_status()
                d = r.json()
                text = d["choices"][0]["message"]["content"]
                u = d.get("usage") or {}
                usage = {"input_tokens": u.get("prompt_tokens", 0), "output_tokens": u.get("completion_tokens", 0)}
            elif p.kind == "anthropic":
                content = [{"type": "text", "text": user}] + [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": x}} for x in b64]
                r = c.post(f"{url}/v1/messages", headers={"x-api-key": p.api_key or "", "anthropic-version": "2023-06-01"},
                           json={"model": model, "max_tokens": 4096, "temperature": 0.2, "system": system,
                                 "messages": [{"role": "user", "content": content}]})
                r.raise_for_status()
                d = r.json()
                text = "".join(part.get("text", "") for part in d.get("content", []) if part.get("type") == "text")
                u = d.get("usage") or {}
                usage = {"input_tokens": u.get("input_tokens", 0), "output_tokens": u.get("output_tokens", 0)}
            elif p.kind == "gemini":
                parts = [{"text": user}] + [{"inline_data": {"mime_type": "image/jpeg", "data": x}} for x in b64]
                r = c.post(f"{url}/v1beta/models/{model}:generateContent", params={"key": p.api_key or ""},
                           json={"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": parts}],
                                 "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}})
                r.raise_for_status()
                d = r.json()
                text = "".join(pt.get("text", "") for pt in d["candidates"][0]["content"]["parts"])
                u = d.get("usageMetadata") or {}
                usage = {"input_tokens": u.get("promptTokenCount", 0), "output_tokens": u.get("candidatesTokenCount", 0)}
            else:
                raise ProviderError(f"Unknown provider kind {p.kind}")
    except httpx.HTTPStatusError as exc:
        raise ProviderError(f"{p.name}: HTTP {exc.response.status_code} - {exc.response.text[:300]}") from exc
    except httpx.HTTPError as exc:
        raise ProviderError(f"{p.name}: connection failed ({type(exc).__name__}: {exc})") from exc
    return parse_json(text), usage


def parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        a, b = text.find("{"), text.rfind("}")
        if a >= 0 and b > a:
            return json.loads(text[a:b + 1])
        raise ProviderError("Provider did not return valid JSON")


def test_connection(p: ProviderConfig) -> dict[str, Any]:
    t = time.time()
    models = []
    try:
        models = list_models(p)
    except Exception as exc:  # noqa: BLE001
        log.info("model listing failed: %s", exc)
    out, usage = chat_json(p, "Reply with JSON only.", 'Return {"ok": true}.', timeout=60)
    return {"ok": bool(out.get("ok", True)), "latency_ms": int((time.time() - t) * 1000), "models": models[:200], "usage": usage}


SYSTEM_PROMPT = """You are a senior short-form video editor and story analyst. You evaluate candidate clips cut from a long video
(podcast, interview, talk, etc.) for standalone short-form publishing. Judge meaning, not keywords. Be honest and critical:
most clips are average. Never invent content that is not in the transcript. Respond with a single JSON object only."""

USER_TEMPLATE = """Video context keywords: {keywords}

For each candidate below you get numbered transcript sentences with timestamps. Sentences marked [CTX] are context just outside
the current clip boundaries; you may move the start/end to any listed sentence if that makes the clip more complete and
self-contained (keep within the allowed duration range).

{blocks}

Return JSON: {{"clips": [{{"id": "<candidate id>", "hook": 0-100, "story": 0-100, "engagement": 0-100, "emotion": 0-100,
"information": 0-100, "standalone": 0-100, "title": "<= 60 chars, faithful, no clickbait lies",
"hook_line": "the actual opening line or best hook sentence from the transcript", "description": "1-2 sentences",
"category": one of ["insight","story","educational","advice","funny","emotional","opinion","qa"],
"reason": "why this works / what is weak (1-2 sentences)", "start_index": <sentence number>, "end_index": <sentence number>}}]}}"""


def build_blocks(cands: list[dict[str, Any]], sentences: list[dict[str, Any]], tolerance: float, ctx_n: int = 3) -> str:
    out = []
    for c in cands:
        i, j = c["i"], c["j"]
        lo, hi = max(0, i - ctx_n), min(len(sentences) - 1, j + ctx_n)
        T = c["target_duration"]
        lines = [f"### Candidate {c['cid']} (target {T:.0f}s, allowed {T * (1 - tolerance):.0f}-{T * (1 + tolerance):.0f}s)"]
        for k in range(lo, hi + 1):
            s = sentences[k]
            tag = "[CTX] " if k < i or k > j else ""
            spk = f"S{int(s.get('speaker', 0)) + 1}: " if "speaker" in s else ""
            lines.append(f"{k}. [{s['s']:.1f}-{s['e']:.1f}] {tag}{spk}{s['text']}")
        out.append("\n".join(lines))
    return "\n\n".join(out)
