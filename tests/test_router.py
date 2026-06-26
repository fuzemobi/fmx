"""SDK-free tests for the generate router — capability matrix, token guard, map-reduce.

No model needed: the Apple branch is never hit and HTTP backends are monkeypatched.
"""

from __future__ import annotations

import asyncio

import pytest

from fmx import backends, router


# --- capability matrix / deny logic -----------------------------------------
def test_default_model_per_mode():
    model, profile, backend = router.resolve("code", None, None)
    assert model == "gpt-oss-120b"
    assert backend == "cerebras"


def test_fmx_code_is_denied_with_reason():
    with pytest.raises(ValueError, match="fails at code"):
        router.resolve("code", "fmx", None)


def test_fmx_reasoning_is_denied():
    with pytest.raises(ValueError, match="0–1/4"):
        router.resolve("reasoning", "fmx", None)


def test_fmx_summarization_is_allowed():
    model, _, backend = router.resolve("summarization", "fmx", None)
    assert (model, backend) == ("fmx", "apple")


def test_unknown_mode_rejected():
    with pytest.raises(ValueError, match="unknown mode"):
        router.resolve("translate", None, None)


def test_unknown_model_needs_explicit_backend():
    with pytest.raises(ValueError, match="explicit backend"):
        router.resolve("code", "some-new-model", None)
    # …but works once a backend is named.
    model, _, backend = router.resolve("code", "some-new-model", "ollama")
    assert (model, backend) == ("some-new-model", "ollama")


def test_estimate_and_strip_fence():
    assert router.estimate_tokens("a" * 40) == 10
    assert router._strip_fence("```python\nx = 1\n```") == "x = 1"


# --- token guard + map-reduce (monkeypatched backend) ------------------------
def _fake_chat(monkeypatch, calls):
    def chat(backend, model, system, prompt, max_tokens, temperature=0.2, num_ctx=None):
        calls.append(len(prompt))
        return {"text": "SHORT SUMMARY", "usage": {}, "ms": 1, "cost_usd": 0.0}

    monkeypatch.setattr(backends, "chat", chat)


def test_oversized_reasoning_escalates_not_truncates(monkeypatch):
    calls: list[int] = []
    _fake_chat(monkeypatch, calls)
    huge = "x" * 600_000  # ~150k tokens > gpt-oss 128k window
    with pytest.raises(ValueError, match="exceeds"):
        asyncio.run(router.route(huge, "reasoning", model="gpt-oss-120b"))
    assert not calls  # refused before any backend call — no silent truncation


def test_oversized_summary_map_reduces(monkeypatch):
    calls: list[int] = []
    _fake_chat(monkeypatch, calls)
    # small-window model so a modest input forces chunking (window > output budget)
    backends.MODELS["tiny-sum"] = {"backend": "ollama", "context": 8000,
                                   "modes": {"summarization"}}
    try:
        out = asyncio.run(router.route("y" * 60_000, "summarization", model="tiny-sum"))
    finally:
        del backends.MODELS["tiny-sum"]
    assert out == "SHORT SUMMARY"
    assert len(calls) > 1  # chunked into multiple summarize passes, then reduced
