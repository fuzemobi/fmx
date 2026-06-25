#!/usr/bin/env python3
"""Capability matrix — fmx vs cloud vs local across 4 task types.

Categories: summarization, coding, reasoning, structured-JSON. Every available backend
runs every category; results are auto-graded into a correctness / speed / cost matrix.

Run:  uv run python benchmarks/run_battery.py
      (fmx needs the CLI on PATH; cerebras needs CEREBRAS_API_KEY; ollama needs a local
       server — any missing backend is skipped.)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness as h  # noqa: E402
import prompts as p  # noqa: E402

OLLAMA_MODEL = "qwen3-coder:30b"


def backends() -> list[tuple[str, str]]:
    """(label, kind) for each available backend. kind drives dispatch + cost."""
    out: list[tuple[str, str]] = []
    if h.fmx_available():
        out.append(("fmx", "fmx"))
    if h.cerebras_available():
        out += [("gpt-oss-120b", "cerebras:gpt-oss-120b"),
                ("glm-4.7", "cerebras:zai-glm-4.7")]
    if h.ollama_available():
        out.append((OLLAMA_MODEL, "ollama"))
    return out


def call(kind: str, prompt: str, max_tokens: int) -> dict:
    if kind == "fmx":
        return h.fmx_respond(prompt, instructions="Follow the instructions exactly.",
                             max_tokens=min(max_tokens, 2000))
    if kind.startswith("cerebras:"):
        return h.cerebras_chat(kind.split(":", 1)[1], prompt, max_tokens=max_tokens)
    return h.ollama_chat(OLLAMA_MODEL, prompt, max_tokens=max_tokens)


def cost_str(kind: str, usage: dict) -> str:
    if kind.startswith("cerebras:"):
        return f"${h.cerebras_cost(kind.split(':', 1)[1], usage):.5f}"
    return "$0"


def main() -> None:
    bes = backends()
    if not bes:
        print("No backends available (need fmx CLI, CEREBRAS_API_KEY, or local Ollama).")
        return
    outdir = Path(__file__).resolve().parent / "results"
    outdir.mkdir(exist_ok=True)
    src_words = len(p.SAMPLE_DOC.read_text().split())

    cats = [
        ("summarization", p.summarization_prompt(), 8000),
        ("coding", p.CODE_PROMPT, 8000),
        ("reasoning", p.REASONING_PROBLEMS[0][1], 8000),  # one rep problem; full rank elsewhere
        ("json", p.JSON_PROMPT, 2000),
    ]
    correct: dict[tuple[str, str], str] = {}
    speed: dict[tuple[str, str], str] = {}
    money: dict[tuple[str, str], str] = {}

    for cat, prompt, mx in cats:
        for label, kind in bes:
            r = call(kind, prompt, mx)
            (outdir / f"out_{cat}_{label}.txt").write_text(r["text"])
            if cat == "summarization":
                verdict = h.grade_summary(r["text"], src_words)
            elif cat == "coding":
                verdict = h.grade_code(r["text"], outdir, label.replace(":", "_"))
            elif cat == "reasoning":
                ok = h.grade_reason(r["text"], p.REASONING_PROBLEMS[0][2])
                verdict = "PASS" if ok else "fail"
            else:
                verdict = h.grade_json(r["text"], p.JSON_EXPECTED)
            correct[(cat, label)] = verdict
            speed[(cat, label)] = f"{r['ms']} ms"
            money[(cat, label)] = cost_str(kind, r["usage"])

    rows = [c[0] for c in cats]
    cols = [b[0] for b in bes]
    h.print_matrix("CORRECTNESS", rows, cols, correct, width=26)
    h.print_matrix("SPEED", rows, cols, speed, width=16)
    h.print_matrix("COST (per call)", rows, cols, money, width=16)
    print("\n* summarization PASS still needs a manual hallucination spot-check.")
    print("reasoning here is one representative problem; run run_reasoning.py for the full rank.")


if __name__ == "__main__":
    main()
