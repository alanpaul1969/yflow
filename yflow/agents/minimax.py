"""
MinimaxAgent — MiniMax M3 native step type for yflow.

Zero external deps. Uses stdlib `urllib.request` to call the M3 Chat
Completions API directly. Yields full control over prompt, model,
max_tokens, temperature.

Configuration (in order of precedence):
  1. step["api_key"]   — explicit per-step override
  2. $YFLOW_MINIMAX_API_KEY  — env var
  3. ~/.config/yflow/auth.json (key: minimax_api_key)  — OIDC-style

Effort → max_tokens / temperature mapping (per v0.4.0 convention):
  low     → 1000 tokens, 0.1
  medium  → 2000 tokens, 0.3
  high    → 4000 tokens, 0.3   (default)
  max     → 8000 tokens, 0.3
"""

from __future__ import annotations

import json as _json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from yflow.memory_injection import build_cold_context

# ------------------------------------------------------------------
# Effort → token / temp defaults
# ------------------------------------------------------------------

EFFORT_PRESETS = {
    "low":    {"max_tokens": 1000, "temperature": 0.1},
    "medium": {"max_tokens": 2000, "temperature": 0.3},
    "high":   {"max_tokens": 4000, "temperature": 0.3},
    "max":    {"max_tokens": 8000, "temperature": 0.3},
}

DEFAULT_BASE_URL = "https://api.minimax.io/v1"
DEFAULT_MODEL = "MiniMax-M3"

# Allow only well-known M3-compatible base URLs by default. Custom hosts must
# be opted in via env var to prevent API-key exfiltration via malicious
# workflow YAMLs (see review finding: minimax.py base_url exfil).
_ALLOWED_BASE_URLS = frozenset({
    "https://api.minimax.io/v1",
    "https://api.MiniMax.tech/v1",
    "https://api.MiniMax.com/v1",
})
_ALLOW_CUSTOM_BASE_URL_ENV = "YFLOW_ALLOW_CUSTOM_BASE_URL"

# ------------------------------------------------------------------
# Auth resolution
# ------------------------------------------------------------------


def _resolve_api_key(step: dict) -> str | None:
    """Resolve API key: step override → env → auth.json."""
    key = step.get("api_key")
    if key:
        return key
    key = os.environ.get("YFLOW_MINIMAX_API_KEY")
    if key:
        return key
    # auth.json fallback
    auth_path = os.path.expanduser("~/.config/yflow/auth.json")
    if os.path.exists(auth_path):
        try:
            with open(auth_path) as f:
                auth = _json.load(f)
            return auth.get("minimax_api_key")
        except Exception:
            pass
    return None


# ------------------------------------------------------------------
# Core API call
# ------------------------------------------------------------------


def _validate_base_url(url: str) -> str:
    """Restrict base_url to known M3-compatible hosts unless explicitly opted in.

    Prevents API-key exfiltration via malicious workflow YAMLs that set
    `base_url` to an attacker-controlled server. See review finding.
    """
    if url in _ALLOWED_BASE_URLS:
        return url
    if os.environ.get(_ALLOW_CUSTOM_BASE_URL_ENV, "").lower() in ("1", "true", "yes"):
        return url
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise ValueError(
            f"base_url must be http(s); got scheme={parsed.scheme!r}. "
            f"Set {_ALLOW_CUSTOM_BASE_URL_ENV}=1 to override."
        )
    if not parsed.netloc:
        raise ValueError(f"base_url missing host: {url!r}")
    raise ValueError(
        f"base_url {url!r} is not in the M3 allowlist. "
        f"Allowed: {sorted(_ALLOWED_BASE_URLS)}. "
        f"Set {_ALLOW_CUSTOM_BASE_URL_ENV}=1 to allow custom hosts."
    )


def call_minimax(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
    max_tokens: int = 4000,
    temperature: float = 0.3,
    timeout: int = 120,
) -> str:
    """Single M3 chat completion call. Returns assistant text.

    Raises:
        ValueError: missing API key or invalid base_url
        RuntimeError: M3 API returned an error or malformed response
        urllib.error.URLError: network failure (DNS, connection refused, timeout)
    """
    if not api_key:
        raise ValueError(
            "No M3 API key. Set YFLOW_MINIMAX_API_KEY env var, "
            "or add to ~/.config/yflow/auth.json: {\"minimax_api_key\": \"sk-...\"}, "
            "or pass api_key in step."
        )

    validated_url = _validate_base_url(base_url)

    req_body = _json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{validated_url}/chat/completions",
        data=req_body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        # e.g. 401/403/429/5xx — re-raise with body context
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        raise RuntimeError(
            f"M3 API HTTP {e.code} {e.reason}: {err_body}"
        ) from e
    except urllib.error.URLError as e:
        # DNS failure, connection refused, timeout, etc.
        raise RuntimeError(
            f"M3 API network error ({type(e.reason).__name__}): {e.reason}"
        ) from e

    try:
        data = _json.loads(raw_body)
    except _json.JSONDecodeError as e:
        raise RuntimeError(
            f"M3 API returned non-JSON body: {raw_body[:200]!r}"
        ) from e

    if not isinstance(data, dict):
        raise RuntimeError(f"M3 API returned non-object body: {raw_body[:200]!r}")
    choices = data.get("choices")
    if not choices or not isinstance(choices, list):
        raise RuntimeError(f"M3 returned no choices: {raw_body[:200]!r}")
    first = choices[0]
    if not isinstance(first, dict) or "message" not in first:
        raise RuntimeError(f"M3 choice missing 'message': {raw_body[:200]!r}")
    message = first["message"]
    if not isinstance(message, dict) or "content" not in message:
        raise RuntimeError(f"M3 message missing 'content': {raw_body[:200]!r}")
    return message["content"]


# ------------------------------------------------------------------
# Step executor (called by engine)
# ------------------------------------------------------------------


def run(step: dict, session: Any) -> str:
    """Execute a `type: minimax` step.

    Step fields:
      prompt:       str (required) — user prompt
      model:        str (default: MiniMax-M3)
      max_tokens:   int (default: from effort preset)
      temperature:  float (default: from effort preset)
      effort:       low|medium|high|max (default: high)
      api_key:      str (optional override)
      base_url:     str (optional override)
      timeout:      int (default: 120)
      context:      str (alternative to 'prompt')
    """
    # Resolve effort preset
    effort = step.get("effort", "high")
    preset = EFFORT_PRESETS.get(effort, EFFORT_PRESETS["high"])

    max_tokens = step.get("max_tokens", preset["max_tokens"])
    temperature = step.get("temperature", preset["temperature"])
    model = step.get("model", DEFAULT_MODEL)
    base_url = step.get("base_url", DEFAULT_BASE_URL)
    timeout = step.get("timeout", 120)

    # Prompt resolution: prefer engine-resolved values (already substituted by
    # the engine) when present, otherwise fall back to resolving now.
    prompt = (
        step.get("_resolved_prompt")
        or step.get("_resolved_context")
        or step.get("prompt")
        or step.get("context", "")
    )
    if not prompt:
        raise ValueError("minimax step requires 'prompt' or 'context' field")
    # Variable resolution (only when not already resolved by engine)
    if (
        session is not None
        and hasattr(session, "resolve")
        and not step.get("_resolved_prompt")
        and not step.get("_resolved_context")
    ):
        prompt = session.resolve(prompt)

    # Cold memory injection (from workflow memory.cold_load, set by engine)
    cold_load = step.get("_cold_load", [])
    if cold_load:
        cold = build_cold_context(cold_load)
        prompt = f"{cold}\n# === Task ===\n\n{prompt}"

    # API key resolution
    api_key = _resolve_api_key(step)
    if not api_key:
        raise ValueError(
            "M3 API key not found. Set YFLOW_MINIMAX_API_KEY, "
            "add to auth.json, or pass api_key in step."
        )

    output = call_minimax(
        prompt,
        model=model,
        api_key=api_key,
        base_url=base_url,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
    )
    return output
