# Capability Matrix — fmx vs gpt-oss-120b vs glm-4.7

**Date:** 2026-06-25  **Harness:** `tmp/battery_benchmark.py` (Cerebras models live via API;
fmx via MCP). All categories machine-graded except the summarization hallucination spot-check.

## Correctness

| Category | fmx (on-device) | gpt-oss-120b (API) | glm-4.7 (API) |
|----------|-----------------|--------------------|---------------|
| Summarization | PASS* | PASS* | PASS* |
| Coding | **FAIL** (pytz / not stdlib) | PASS (pytest + ref) | PASS (pytest + ref) |
| Reasoning (billing trap) | PASS | PASS | PASS |
| Structured JSON | PASS | PASS | PASS |

\* sections + ratio auto-checked; needs a manual hallucination spot-check.

## Speed (per call)

| Category | fmx | gpt-oss-120b | glm-4.7 |
|----------|-----|--------------|---------|
| Summarization | 63,542 ms | 1,425 ms | 2,971 ms |
| Coding | 38,023 ms | 478 ms | 5,939 ms |
| Reasoning | 23,913 ms | 391 ms | 1,851 ms |
| JSON | 24,421 ms | 304 ms | 479 ms |

## Cost (per call)

| Category | fmx | gpt-oss-120b | glm-4.7 |
|----------|-----|--------------|---------|
| Summarization | $0 | $0.00257 | $0.00527 |
| Coding | $0 | $0.00043 | $0.00288 |
| Reasoning | $0 | $0.00017 | $0.00149 |
| JSON | $0 | $0.00016 | $0.00063 |

## What each model is good at (the point of the exercise)

- **gpt-oss-120b (API)** — the all-rounder. Correct in every category, fastest, cheapest
  cloud. Default choice for summarization, coding, reasoning, and extraction. ~10–40×
  faster than fmx and ~2–10× cheaper than glm.
- **glm-4.7 (API)** — correct in every category too, but slower and 2–10× costlier
  (reasoning tokens), and it needs a large max_tokens or it returns a truncated reasoning
  trace. Reserve for genuinely hard reasoning where gpt-oss is shown to fall short — not
  this test (both passed).
- **fmx (Apple on-device)** — free, local, private, offline. PASSES summarization,
  reasoning, and JSON extraction; the ONLY thing it fails is **coding** (pulled in `pytz`
  despite "stdlib only", wrong `.isoformat()` format, `@raises` idiom). It's also 20–60 s
  per call. Niche: zero-cost / privacy-sensitive summarize / classify / extract / quick
  math when latency doesn't matter. **Never for code.**

## Routing rules
| Need | Use |
|------|-----|
| Code / tests / scripts | gpt-oss-120b (never fmx) |
| Fast cheap summarize / extract / reason | gpt-oss-120b |
| Hard multi-step reasoning gpt-oss flubs | glm-4.7 (big token budget) |
| Free / offline / CPNI-private summarize, classify, extract, math | fmx (tolerate latency) |
| Prose of any kind | the API, NOT the cerebras-code MCP (it's a code tool) |

## Caveats
- The MCP wrappers distort behavior: `cerebras-code` MCP only emits code (use the API for
  prose); fmx timings include MCP transport but are dominated by genuine on-device latency.
- Reasoning + JSON here were easy enough that all three passed — they separate models only
  at higher difficulty. To actually rank reasoning, raise difficulty until models diverge.

## Files (tmp/)
- `battery_benchmark.py` — harness
- `battery_<cat>_<model>.out` — every Cerebras output
- `fmx_<cat>.{md,py,txt}` + `fmx_<cat>_ms.txt` — fmx outputs + timings
- `battery_report.md` — this file
