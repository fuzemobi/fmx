# Hard Reasoning Ranking — 4 trap problems (score 0–4)

**Date:** 2026-06-25  **Harness:** `tmp/reasoning_rank.py`
Contestants: fmx (on-device MCP), gpt-oss-120b + glm-4.7 (Cerebras API),
qwen3-coder:30b (local Ollama). Cerebras budget raised to 16k tokens for fairness.
Grading: the model's **final answer line** must contain the expected value (whole-transcript
matching was rejected — it false-passed on tokens quoted from the problem clues).

Problems: A=tiered plan + surcharge-above-$40 (→ $90.60), B=DST/timezone call-end in UTC
(→ 2026-03-08T08:00:00Z), C=logic grid (→ CH3), D=plan break-even MB (→ 1000).

## Result

| Problem | fmx | gpt-oss-120b | glm-4.7 | qwen3-coder:30b (local) |
|---------|-----|--------------|---------|--------------------------|
| A (tiered+surcharge) | fail | PASS | PASS | PASS |
| B (DST→UTC) | fail | PASS | PASS | **fail** |
| C (logic grid) | fail | PASS | **fail\*** | PASS |
| D (break-even) | PASS | PASS | PASS | PASS |
| **SCORE** | **1/4** | **4/4** | **3/4\*** | **3/4** |
| Total time | 122.8 s | 2.4 s | 12.8 s | 17.8 s |
| Cost | $0 | $0.00166 | $0.02250 | $0 |

## Ranking (by delivered correct answers)
1. **gpt-oss-120b — 4/4, 2.4 s, $0.0017.** Decisive winner: solved every trap, concise,
   ~5–7× faster and ~13× cheaper than glm. Best reasoner *and* best value.
2. **qwen3-coder:30b (local) — 3/4, free, ~18 s.** Impressive for a *code*-tuned local
   model: nailed the tiered-billing, logic-grid, and break-even traps. Only missed the DST
   problem (computed 07:30Z instead of 08:00Z — bungled the spring-forward). Zero cost,
   fully private/offline.
3. **glm-4.7 — 3/4 delivered, but really a termination problem.** It actually *reached* the
   correct answer on all four (incl. C: "carrier A uses CH3"), but it chronically
   over-reasons and never emits a final answer line — on C it blew past even 16k tokens
   (56 KB of output) still second-guessing. \*So C scores fail because **no answer was
   delivered**, not because it couldn't solve it. Slowest-to-useful and ~13× the cost of
   gpt-oss. Practical risk: it can burn a big token budget and still not answer.
4. **fmx (on-device) — 1/4, 123 s.** Only got the simplest algebra (break-even). Botched
   tiered arithmetic (104.40), DST (07:00), and the logic grid (CH2). Not a reasoner for
   hard, multi-step problems.

## Key findings
- The earlier "all 3 pass" was an artifact of an easy problem + loose grading. With traps
  and answer-line grading, models **diverge cleanly**: gpt-oss 4 / qwen 3 / glm 3 / fmx 1.
- **gpt-oss-120b is the reasoning pick** — accuracy, speed, and cost all best.
- **glm-4.7's weakness is termination, not intellect** — it needs a hard "answer concisely
  in ≤N tokens" constraint or it runs away. Until then it's the worst value here.
- **qwen3-coder:30b punches above its label** — a local code model scoring 3/4 on reasoning
  is a strong free/offline option. For dedicated reasoning, a reasoning-tuned local model
  (e.g. `qwen3:32b` or `deepseek-r1:32b`) would likely beat it on the DST-type traps —
  worth pulling if local reasoning matters.

## Files (tmp/)
- `reasoning_rank.py` — harness
- `reason_<A-D>_<model>.out` — every cloud/local transcript
- `fmx_reason_<A-D>.txt` + `_ms.txt` — fmx transcripts + timings
- `reasoning_rank_report.md` — this file
