#!/usr/bin/env python3
"""Unified multi-provider chat client for the Stage 1 experiment.

Exposes a single `complete(provider, model, system, user) -> str` that returns
the model's raw text (expected to be JSON). Each provider is imported lazily so a
missing SDK for one provider does not break the others. API keys come from .env:
OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY.

Provider quirks handled here:
- OpenAI gpt-5.x: use `max_completion_tokens` (not `max_tokens`) and omit
  `temperature` (the series only accepts the default).
- Anthropic: JSON is requested via the prompt; text is joined from content blocks.
- Google genai: JSON via `response_mime_type`, system via `system_instruction`.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

load_dotenv(str(Path(__file__).resolve().parent.parent.parent / ".env"), override=False)

RAW_OUTPUT_DIR = Path("results/raw_experiment_outputs")

# Default model ids per provider (override via env or CLI).
DEFAULT_MODELS = {
    "openai": os.getenv("EXP_OPENAI_MODEL", "gpt-5.5"),
    "anthropic": os.getenv("EXP_ANTHROPIC_MODEL", "claude-opus-4-8"),
    "google": os.getenv("EXP_GOOGLE_MODEL", "gemini-3.5-flash"),
}

_clients: dict[str, object] = {}


class MissingApiKeyError(RuntimeError):
    pass


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise MissingApiKeyError(f"{key} is not set in the environment/.env")
    return val


# --------------------------------------------------------------------------- #
# provider calls
# --------------------------------------------------------------------------- #

def _openai_client():
    if "openai" not in _clients:
        from openai import OpenAI
        _clients["openai"] = OpenAI(api_key=_require("OPENAI_API_KEY"))
    return _clients["openai"]


def _anthropic_client():
    if "anthropic" not in _clients:
        import anthropic
        _clients["anthropic"] = anthropic.Anthropic(api_key=_require("ANTHROPIC_API_KEY"))
    return _clients["anthropic"]


def _google_client():
    if "google" not in _clients:
        from google import genai
        _clients["google"] = genai.Client(api_key=_require("GOOGLE_API_KEY"))
    return _clients["google"]


def _call_openai(model: str, system: str, user: str, max_tokens: int) -> str:
    resp = _openai_client().chat.completions.create(
        model=model,
        max_completion_tokens=max_tokens,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return resp.choices[0].message.content or ""


def _call_anthropic(model: str, system: str, user: str, max_tokens: int) -> str:
    resp = _anthropic_client().messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")


def _call_google(model: str, system: str, user: str, max_tokens: int) -> str:
    from google.genai import types
    resp = _google_client().models.generate_content(
        model=model,
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            max_output_tokens=max_tokens,
        ),
    )
    return resp.text or ""


_DISPATCH = {"openai": _call_openai, "anthropic": _call_anthropic, "google": _call_google}


def _is_retryable(exc: Exception) -> bool:
    name = type(exc).__name__
    transient = {
        "APIConnectionError", "APITimeoutError", "RateLimitError",
        "InternalServerError", "APIError", "ServiceUnavailable",
        "ResourceExhausted", "DeadlineExceeded", "ServerError", "OverloadedError",
    }
    if name in transient:
        return True
    msg = str(exc).lower()
    return any(s in msg for s in ("rate limit", "overloaded", "timeout", "503", "529", "500"))


@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    reraise=True,
)
def _call_with_retry(provider: str, model: str, system: str, user: str, max_tokens: int) -> str:
    try:
        return _DISPATCH[provider](model, system, user, max_tokens)
    except Exception as exc:  # noqa: BLE001
        if _is_retryable(exc):
            raise
        # Non-transient (bad request, auth, unknown model): do not waste retries.
        raise RuntimeError(f"{provider}/{model} non-retryable error: {exc}") from exc


def complete(
    provider: str,
    model: Optional[str] = None,
    *,
    system: str,
    user: str,
    max_tokens: int = 2048,
    raw_tag: Optional[str] = None,
) -> str:
    """Return raw text (expected JSON) from the given provider/model."""
    if provider not in _DISPATCH:
        raise ValueError(f"unknown provider: {provider} (valid: {list(_DISPATCH)})")
    model = model or DEFAULT_MODELS[provider]
    content = _call_with_retry(provider, model, system, user, max_tokens)
    if raw_tag:
        RAW_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_OUTPUT_DIR / f"{raw_tag}.txt").write_text(content, encoding="utf-8")
    return content


# --------------------------------------------------------------------------- #
# tolerant JSON parsing
# --------------------------------------------------------------------------- #

def parse_json_loose(text: str) -> dict:
    """Parse model output into a dict, tolerating code fences / surrounding prose."""
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise
