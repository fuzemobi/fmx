"""Backend registry and uniform call layer for the `generate` router tool.

SDK-free: this module only speaks HTTP (urllib) + the model registry. The Apple
on-device backend is handled in ``router.py`` (it needs ``core`` / the SDK and is
async), so this module imports cleanly on machines without ``apple-fm-sdk``.

Three backend kinds:
- ``openai`` — any OpenAI-compatible ``/v1/chat/completions`` endpoint (Cerebras,
  vLLM, LM Studio, OpenAI itself, …). Cerebras needs a spoofed curl User-Agent.
- ``ollama`` — local Ollama via the **native** ``/api/chat`` so we can set
  ``options.num_ctx`` (the OpenAI-compat endpoint silently truncates at ~4k).
- ``apple`` — fmx on-device; resolved in ``router.py``.

Add another OpenAI-compatible backend by adding a ``BACKENDS`` entry + its
``MODELS``, or at runtime via the ``FMX_OPENAI_*`` env vars (see ``_env_backend``).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

# --- backend definitions -----------------------------------------------------
# key_env: env var names checked in order (also read from ~/.secrets/api-keys.env
# and ~/.env). ua: optional User-Agent override (Cerebras 403s the urllib default).
BACKENDS: dict[str, dict] = {
    "cerebras": {
        "kind": "openai",
        "base_url": "https://api.cerebras.ai/v1",
        "key_env": ("CEREBRAS_API_KEY", "CEREBRAS_APIKEY"),
        "ua": "curl/8",
    },
    "ollama": {"kind": "ollama", "base_url": "http://localhost:11434"},
    "apple": {"kind": "apple"},
}

# USD per 1M tokens (input, output). Absent → cost reported as 0.
PRICING: dict[str, tuple[float, float]] = {
    "gpt-oss-120b": (0.25, 0.69),
    "zai-glm-4.7": (0.40, 1.20),
}

# model -> profile. context = window in tokens; modes = task modes this model is
# trusted for (see benchmarks/FINDINGS.md); needs_cap = must send a max_tokens cap
# or it runs away (glm-4.7). Unregistered models still work via an explicit backend.
MODELS: dict[str, dict] = {
    "gpt-oss-120b": {
        "backend": "cerebras", "context": 128_000,
        "modes": {"reasoning", "summarization", "code", "extract"},
    },
    "zai-glm-4.7": {
        "backend": "cerebras", "context": 128_000,
        "modes": {"reasoning", "summarization", "code", "extract"}, "needs_cap": True,
    },
    "qwen3-coder:30b": {
        "backend": "ollama", "context": 256_000,
        "modes": {"summarization", "code", "extract"},  # reasoning ⚠️ misses DST traps
    },
    "fmx": {
        "backend": "apple", "context": 4_000,
        "modes": {"summarization", "extract"},  # never code / hard reasoning
    },
}


def _env_backend() -> None:
    """Register one extra OpenAI-compatible backend from env, if configured.

    FMX_OPENAI_BASE_URL, FMX_OPENAI_KEY_ENV (default OPENAI_API_KEY),
    FMX_OPENAI_MODELS (comma list), FMX_OPENAI_CONTEXT (default 128000).
    Custom models are trusted for all modes — we don't know their weak spots.
    """
    base = os.environ.get("FMX_OPENAI_BASE_URL")
    if not base or "openai" in BACKENDS:
        return
    BACKENDS["openai"] = {
        "kind": "openai", "base_url": base.rstrip("/"),
        "key_env": (os.environ.get("FMX_OPENAI_KEY_ENV", "OPENAI_API_KEY"),),
    }
    ctx = int(os.environ.get("FMX_OPENAI_CONTEXT", "128000"))
    for m in (os.environ.get("FMX_OPENAI_MODELS") or "").split(","):
        m = m.strip()
        if m:
            MODELS.setdefault(m, {
                "backend": "openai", "context": ctx,
                "modes": {"reasoning", "summarization", "code", "extract"},
            })


_env_backend()


# --- key loading -------------------------------------------------------------
def _load_key(env_names: tuple[str, ...]) -> str | None:
    """Read an API key from the environment or ~/.secrets/api-keys.env / ~/.env."""
    for name in env_names:
        if name and os.environ.get(name):
            return os.environ[name]
    targets = set(env_names)
    for f in (Path.home() / ".secrets/api-keys.env", Path.home() / ".env"):
        if not f.exists():
            continue
        for ln in f.read_text().splitlines():
            ln = ln.strip()
            ln = ln[len("export "):] if ln.startswith("export ") else ln
            if "=" in ln and not ln.startswith("#"):
                k, _, v = ln.partition("=")
                if k.strip() in targets:
                    return v.strip().strip('"').strip("'")
    return None


def available(backend: str) -> bool:
    """Whether a backend can be reached right now (key present / daemon up)."""
    cfg = BACKENDS.get(backend)
    if not cfg:
        return False
    kind = cfg["kind"]
    if kind == "apple":
        return True  # real check is core.availability(), done at call time
    if kind == "ollama":
        try:
            urllib.request.urlopen(cfg["base_url"] + "/api/tags", timeout=2)
            return True
        except (urllib.error.URLError, OSError):
            return False
    return _load_key(cfg.get("key_env", ())) is not None


# --- HTTP calls --------------------------------------------------------------
def _post(url: str, payload: dict, headers: dict, timeout: int = 300) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    return {"raw": d, "ms": round((time.time() - t0) * 1000)}


def cost_usd(model: str, usage: dict) -> float:
    if not usage or model not in PRICING:
        return 0.0
    pin, pout = PRICING[model]
    return (usage.get("prompt_tokens", 0) / 1e6 * pin
            + usage.get("completion_tokens", 0) / 1e6 * pout)


def chat(backend: str, model: str, system: str | None, prompt: str,
         max_tokens: int, temperature: float = 0.2, num_ctx: int | None = None) -> dict:
    """Synchronous chat call. Returns {text, usage, ms, cost_usd}.

    ``apple`` is not handled here — the router calls the SDK directly (async).
    """
    cfg = BACKENDS[backend]
    messages = ([{"role": "system", "content": system}] if system else []) + \
        [{"role": "user", "content": prompt}]

    if cfg["kind"] == "ollama":
        # Native /api/chat so we can raise num_ctx (OpenAI-compat endpoint truncates at ~4k).
        options = {"temperature": temperature, "num_predict": max_tokens}
        if num_ctx:
            options["num_ctx"] = num_ctx
        out = _post(cfg["base_url"] + "/api/chat",
                    {"model": model, "messages": messages, "stream": False, "options": options},
                    {"Content-Type": "application/json"})
        d = out["raw"]
        usage = {"prompt_tokens": d.get("prompt_eval_count", 0),
                 "completion_tokens": d.get("eval_count", 0)}
        return {"text": d.get("message", {}).get("content", ""),
                "usage": usage, "ms": out["ms"], "cost_usd": 0.0}

    # openai-compatible
    headers = {"Content-Type": "application/json"}
    key = _load_key(cfg.get("key_env", ()))
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if cfg.get("ua"):
        headers["User-Agent"] = cfg["ua"]
    out = _post(cfg["base_url"] + "/chat/completions",
                {"model": model, "messages": messages,
                 "max_tokens": max_tokens, "temperature": temperature}, headers)
    d = out["raw"]
    msg = d["choices"][0]["message"]
    usage = d.get("usage", {})
    return {"text": msg.get("content") or msg.get("reasoning") or "",
            "usage": usage, "ms": out["ms"], "cost_usd": cost_usd(model, usage)}
