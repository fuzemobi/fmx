"""The routing seam for the `generate` MCP tool — mode × model capability + discipline.

One entry point, ``route()``. It encodes what benchmarks/MODEL_ROUTING.md describes
as prose: pick/validate a backend by task ``mode``, deny unsupported (mode, model)
pairs with a findings-cited reason, bake in the per-mode prompt/param lessons, and
fit the input to the target context window without losing context (route up, or
map-reduce for summaries — never silent truncation).

Apple/SDK imports are deferred into the apple branch so this module loads anywhere.
"""

from __future__ import annotations

import asyncio
import sys

from . import backends

MODES = ("reasoning", "summarization", "code", "extract")

# Per-mode default model (first choice from FINDINGS.md).
DEFAULT_MODEL = {
    "code": "gpt-oss-120b",
    "reasoning": "gpt-oss-120b",
    "summarization": "gpt-oss-120b",
    "extract": "fmx",
}

# Per-mode system prompt — the discipline the benchmarks learned, baked in so callers
# can't repeat the mistakes (fmx invents detail; models add fences; tests use decorators).
MODE_SYSTEM = {
    "code": (
        "You are a precise coding assistant. Output ONLY code — no prose, no markdown "
        "fences. Prefer the standard library unless told otherwise. In tests use "
        "`with pytest.raises(...)`, never the @raises decorator."
    ),
    "summarization": (
        "Summarize the source faithfully. This is condensation, NOT expansion: use only "
        "facts present in the source, invent nothing, add no detail not in the text. "
        "No markdown fences."
    ),
    "reasoning": (
        "Solve step by step, then end with one final line `ANSWER: <answer>`. Be concise "
        "and stay within the token budget — do not second-guess past the answer."
    ),
    "extract": (
        "Extract the requested fields as strict, minified JSON only. No prose, no markdown "
        "fences. Use correct JSON types (numbers unquoted)."
    ),
}

# Per-mode default output cap (tokens). Reasoning is capped on purpose — glm-4.7 runs
# away uncapped (FINDINGS.md #5). Override per call with max_tokens.
MODE_MAX_TOKENS = {"code": 4000, "summarization": 2000, "reasoning": 2000, "extract": 1000}

# Friendlier, evidence-cited denials for the headline cases.
DENY_REASON = {
    ("fmx", "code"): (
        "fmx (on-device) fails at code — it pulls non-stdlib deps and emits +00:00 instead "
        "of Z (FINDINGS.md). Route code to gpt-oss-120b (Cerebras) or qwen3-coder:30b (Ollama)."
    ),
    ("fmx", "reasoning"): (
        "fmx (on-device) scores 0–1/4 on hard reasoning (FINDINGS.md). Route reasoning to "
        "gpt-oss-120b (Cerebras)."
    ),
}


def estimate_tokens(text: str) -> int:
    """Cheap, conservative token estimate (~4 chars/token)."""
    # ponytail: chars/4 heuristic, swap for a real tokenizer if routing gets tight.
    return len(text) // 4


def _strip_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines)
    return t.strip()


def resolve(mode: str, model: str | None, backend: str | None) -> tuple[str, dict, str]:
    """Validate (mode, model, backend) and return (model, profile, backend).

    Raises ValueError on an unknown mode, an unresolvable model, or a (mode, model)
    pair the model isn't trusted for.
    """
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; choose one of {', '.join(MODES)}")
    model = model or DEFAULT_MODEL[mode]

    profile = backends.MODELS.get(model)
    if profile is None:
        # Unregistered model: caller must name the backend; trust it for the mode.
        if not backend:
            raise ValueError(
                f"unknown model {model!r}; pass an explicit backend "
                f"(one of {', '.join(backends.BACKENDS)}) for ad-hoc models"
            )
        return model, {"backend": backend, "context": None, "modes": set(MODES)}, backend

    backend = profile["backend"]
    if mode not in profile["modes"]:
        reason = DENY_REASON.get((model, mode)) or (
            f"{model} (backend {backend}) is not trusted for mode {mode!r} "
            f"(supports: {', '.join(sorted(profile['modes']))})."
        )
        raise ValueError(reason)
    return model, profile, backend


async def _call(backend: str, model: str, system: str, prompt: str,
                max_tokens: int, num_ctx: int | None) -> dict:
    """Dispatch one call: apple in-process (async SDK), everything else over HTTP."""
    if backend == "apple":
        from . import core  # deferred: SDK only imported when actually targeting fmx

        ok, message = core.availability()
        if not ok:
            raise RuntimeError(message)
        from .respond import make_options

        session = core.make_session(system)
        options = make_options(0.2, max_tokens)
        text = str(await session.respond(prompt, options=options))
        return {"text": text, "usage": {}, "ms": 0, "cost_usd": 0.0}

    # HTTP backends are synchronous urllib — run off the event loop.
    return await asyncio.to_thread(
        backends.chat, backend, model, system, prompt, max_tokens, 0.2, num_ctx
    )


async def _map_reduce(backend: str, model: str, system: str, prompt: str,
                      window: int, budget: int) -> dict:
    """Summarize an over-window input losslessly-ish: chunk → summarize → reduce.

    Beats truncation (which loses context) and headroom-compress (lossy, and the
    model can't retrieve mid-call). Each pass shrinks the text until it fits.
    """
    # Cap the per-pass output budget at half the window so the reduce always converges
    # (an output budget >= window would mean even empty text never "fits").
    budget = min(budget, max(256, window // 2))
    chunk_tokens = max(256, window - budget - 256)
    chunk_chars = chunk_tokens * 4
    total = 0.0
    text = prompt
    while estimate_tokens(text) + budget > window:
        chunks = [text[i:i + chunk_chars] for i in range(0, len(text), chunk_chars)]
        summaries = []
        for c in chunks:
            r = await _call(backend, model, system, c, budget, window)
            summaries.append(_strip_fence(r["text"]))
            total += r["cost_usd"]
        text = "\n\n".join(summaries)
    final = await _call(backend, model, system, text, budget, window)
    final["cost_usd"] += total
    return final


async def route(prompt: str, mode: str, model: str | None = None,
                backend: str | None = None, max_tokens: int | None = None) -> str:
    """Route one generation by task mode. The single entry point for `generate`.

    Validates mode+model, denies unsupported pairs, applies per-mode discipline,
    fits the input to the context window, calls the backend, and returns clean text.
    Usage + cost are logged to stderr (FINDINGS.md: always log token/cost).
    """
    model, profile, backend = resolve(mode, model, backend)
    system = MODE_SYSTEM[mode]
    budget = max_tokens or MODE_MAX_TOKENS[mode]
    # glm-4.7 (and any needs_cap model) must never run uncapped.
    if profile.get("needs_cap"):
        budget = min(budget, MODE_MAX_TOKENS[mode])

    window = profile.get("context")
    if window and estimate_tokens(prompt) + budget > window:
        if mode == "summarization":
            result = await _map_reduce(backend, model, system, prompt, window, budget)
        else:
            raise ValueError(
                f"input ~{estimate_tokens(prompt)} tokens + {budget} output exceeds "
                f"{model}'s {window}-token window. Route {mode} to a larger-context model "
                f"(e.g. gpt-oss-120b, 128k), or pre-summarize the context."
            )
    else:
        result = await _call(backend, model, system, prompt, budget, window)

    print(f"[fmx generate] mode={mode} model={model} backend={backend} "
          f"tokens={result['usage']} cost=${result['cost_usd']:.4f} {result['ms']}ms",
          file=sys.stderr)
    return _strip_fence(result["text"])


def capabilities() -> dict:
    """The full mode × model matrix as data — backs the `list_capabilities` tool."""
    return {
        "modes": list(MODES),
        "defaults": DEFAULT_MODEL,
        "models": {
            m: {"backend": p["backend"], "context": p["context"],
                "modes": sorted(p["modes"]), "available": backends.available(p["backend"]),
                "needs_cap": p.get("needs_cap", False)}
            for m, p in backends.MODELS.items()
        },
    }
