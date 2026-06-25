#!/usr/bin/env python3
"""Hard reasoning ranking — 4 trap problems, scored 0-4 per backend.

Designed so models diverge instead of all passing. Each problem has one verifiable
answer; grading reads only the final ANSWER line.

Run:  uv run python benchmarks/run_reasoning.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness as h  # noqa: E402
import prompts as p  # noqa: E402

OLLAMA_MODEL = "qwen3-coder:30b"
# glm-4.7 over-reasons; give cloud models a large budget or it truncates before answering.
CEREBRAS_MAX_TOKENS = 16000


def backends() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if h.fmx_available():
        out.append(("fmx", "fmx"))
    if h.cerebras_available():
        out += [("gpt-oss-120b", "cerebras:gpt-oss-120b"),
                ("glm-4.7", "cerebras:zai-glm-4.7")]
    if h.ollama_available():
        out.append((OLLAMA_MODEL, "ollama"))
    return out


def call(kind: str, prompt: str) -> dict:
    if kind == "fmx":
        return h.fmx_respond(prompt, max_tokens=2000)
    if kind.startswith("cerebras:"):
        return h.cerebras_chat(kind.split(":", 1)[1], prompt, max_tokens=CEREBRAS_MAX_TOKENS)
    return h.ollama_chat(OLLAMA_MODEL, prompt, max_tokens=8000)


def main() -> None:
    bes = backends()
    if not bes:
        print("No backends available.")
        return
    outdir = Path(__file__).resolve().parent / "results"
    outdir.mkdir(exist_ok=True)

    cell: dict[tuple[str, str], str] = {}
    score: dict[str, int] = {b[0]: 0 for b in bes}
    secs: dict[str, float] = {b[0]: 0.0 for b in bes}
    cost: dict[str, float] = {b[0]: 0.0 for b in bes}

    for pid, prompt, expected in p.REASONING_PROBLEMS:
        for label, kind in bes:
            r = call(kind, prompt)
            ok = h.grade_reason(r["text"], expected)
            cell[(pid, label)] = "PASS" if ok else "fail"
            score[label] += int(ok)
            secs[label] += r["ms"] / 1000
            if kind.startswith("cerebras:"):
                cost[label] += h.cerebras_cost(kind.split(":", 1)[1], r["usage"])
            (outdir / f"reason_{pid}_{label}.txt").write_text(r["text"])

    rows = [pid for pid, _, _ in p.REASONING_PROBLEMS]
    cols = [b[0] for b in bes]
    h.print_matrix("HARD REASONING (per-problem)", rows, cols, cell, width=18)
    print(f"{'SCORE':<14}" + "".join(f"{str(score[c]) + '/4':>18}" for c in cols))
    print(f"{'TIME(s)':<14}" + "".join(f"{secs[c]:>18.1f}" for c in cols))
    print(f"{'COST($)':<14}" + "".join(f"{cost[c]:>18.5f}" for c in cols))
    print("\nA=tiered+threshold(90.60)  B=DST/UTC(08:00:00Z)  "
          "C=logic grid(CH3)  D=break-even(1000)")


if __name__ == "__main__":
    main()
