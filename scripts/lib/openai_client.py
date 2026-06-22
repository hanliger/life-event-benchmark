"""Thin wrapper around the OpenAI client for Stage 1 generation.

Responsibilities:
  - Load `.env` (python-dotenv) and read model settings from the environment.
  - Provide `generate_text(...)` with retry/backoff via tenacity.
  - Persist every raw model response to data/generated/raw_model_outputs/.
  - Never print or log API keys.

The module is import-safe even when the `openai` package or API key is missing:
the error is only raised when an actual API call is attempted.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

# Load .env once at import time. `override=False` keeps any already-exported
# shell variables authoritative.
load_dotenv(override=False)

RAW_OUTPUT_DIR = Path("data/generated/raw_model_outputs")

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TEMPERATURE = 0.8
DEFAULT_MAX_OUTPUT_TOKENS = 3000


class MissingApiKeyError(RuntimeError):
    """Raised when no OPENAI_API_KEY is available for a real API call."""


def get_model() -> str:
    return os.getenv("OPENAI_MODEL") or DEFAULT_MODEL


def get_temperature() -> float:
    val = os.getenv("OPENAI_TEMPERATURE")
    return float(val) if val is not None else DEFAULT_TEMPERATURE


def get_max_output_tokens() -> int:
    val = os.getenv("OPENAI_MAX_OUTPUT_TOKENS")
    return int(val) if val is not None else DEFAULT_MAX_OUTPUT_TOKENS


def get_concurrency() -> int:
    val = os.getenv("OPENAI_CONCURRENCY")
    return int(val) if val is not None else 3


def _require_api_key() -> str:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise MissingApiKeyError(
            "OPENAI_API_KEY is not set. Create a `.env` file (see .env.example) "
            "with OPENAI_API_KEY=... or export it in your shell before running "
            "generation with --execute."
        )
    return key


def _client():
    """Construct an OpenAI client. Imported lazily so the module loads without openai."""
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - defensive
        raise RuntimeError(
            "The `openai` package is required for --execute. Install with "
            "`pip install -r requirements.txt`."
        ) from exc
    _require_api_key()
    return OpenAI()


def _save_raw(tag: str, content: str) -> None:
    """Persist a raw response. `tag` should already be filesystem-safe."""
    RAW_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_OUTPUT_DIR / f"{tag}.txt"
    path.write_text(content, encoding="utf-8")


def _is_retryable(exc: Exception) -> bool:
    name = type(exc).__name__
    return name in {
        "APIConnectionError",
        "APITimeoutError",
        "RateLimitError",
        "InternalServerError",
        "APIError",
    }


@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    reraise=True,
)
def _call_chat(
    client,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_output_tokens: int,
) -> str:
    """Call the Chat Completions API with JSON-object response format."""
    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=max_output_tokens,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return resp.choices[0].message.content or ""


def generate_text(
    system_prompt: str,
    user_prompt: str,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_output_tokens: Optional[int] = None,
    raw_tag: Optional[str] = None,
) -> str:
    """Generate text from the configured OpenAI model.

    Returns the raw text content of the model response. The response is also
    persisted under data/generated/raw_model_outputs/ when `raw_tag` is given.
    """
    model = model or get_model()
    temperature = get_temperature() if temperature is None else temperature
    max_output_tokens = get_max_output_tokens() if max_output_tokens is None else max_output_tokens

    client = _client()
    content = _call_chat(
        client,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )
    if raw_tag:
        _save_raw(raw_tag, content)
    return content
