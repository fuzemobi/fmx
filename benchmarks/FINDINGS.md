# Findings — model ranking & lessons (2026-06-25)

Combined history from the benchmark sessions. Backends: **fmx** (Apple on-device, via CLI
/ MCP `respond`), **gpt-oss-120b** + **zai-glm-4.7** (Cerebras API — the only two models that
key serves), **qwen3-coder:30b** (local Ollama).

## Per-model ranking

### 1. gpt-oss-120b (Cerebras) — the all-rounder ⭐
- **Summarization:** PASS — complete, faithful, kept tables/edge cases.
- **Coding:** PASS — `to_zulu()` correct (pytest + independent ref-check), right idioms, stdlib-only.
- **Reasoning:** **4/4 every run**, ~2 s total, ~$0.0017. Only model that consistently nails all traps.
- **JSON extraction:** PASS — correct types (int mcc/mnc), no chatter.
- **Verdict:** correct in every category, fastest, cheapest cloud. Default for almost everything.

### 2. qwen3-coder:30b (local Ollama) — best free/offline option
- **Reasoning:** 3/4 consistently — gets tiered billing, logic grid, break-even; **misses the
  DST/timezone trap** (computes 07:30Z instead of 08:00Z). Code-tuned, so the non-code trap is its gap.
- **Cost $0, fully offline/private.** ~17–25 s per reasoning set on this Mac.
- **Verdict:** strong local default for code + general reasoning. For dedicated local reasoning,
  a reasoning-tuned model (`qwen3:32b`, `deepseek-r1:32b`) would likely close the DST gap.

### 3. glm-4.7 (Cerebras) — accurate but won't shut up ⚠️
- Reaches correct answers but **chronically fails to terminate**: keeps second-guessing and
  gets truncated before emitting an answer line — even at a 16k-token budget (56 KB of output).
- **High variance + expensive:** across runs scored 2/4–3/4, 12–50 s, and **up to $0.04 for 4
  questions** (~13–25× gpt-oss). Reasoning capability is real; usability/value is poor.
- **Verdict:** avoid unless you hard-cap output ("answer in ≤N tokens"). Worst value here.

### 4. fmx (Apple on-device) — narrow but free/private
- **Summarization:** PASS after an anti-invention rule (without it, it invented a pipeline-stage
  description). **Coding: FAIL** — pulled in `pytz` despite "stdlib only", used `.isoformat()`
  (→ `+00:00`, not `Z`), `@raises` decorator instead of `with pytest.raises`.
- **Reasoning:** 0/4–1/4 on the hard set — botched tiered arithmetic, DST, and the logic grid;
  only sometimes gets simple break-even algebra. **JSON: PASS** (wrapped in fences despite the rule).
- **Latency 20–60 s/call; small context.**
- **Verdict:** good for summarize / classify / extract / quick math when free+private+offline
  matter and latency doesn't. **Never for code. Never for hard reasoning. Never for long inputs.**

## What we learned (the meta-lessons)

1. **Match the tool to the task, not the brand.** The `mcp__cerebras-code__write` MCP is a
   *code* tool — it ignored prose-summarization prompts and emitted only code, twice, regardless
   of prompt wording. Root cause was the **MCP wrapper, not the model**: the same gpt-oss-120b via
   the raw API summarized perfectly. → For prose, use the API; reserve the code MCP for code.

2. **fmx invents detail when asked to expand.** A small model fills gaps with plausible-but-wrong
   facts. Fix with an explicit "condensation not expansion; use only the source" rule. Even then,
   spot-check — it still made a transcription error (`1` → `130` exit code).

3. **glm-4.7's failure mode is termination, not intellect.** Give it a hard output cap or it runs
   away. Default-uncapped, it's slow and expensive and may never answer.

4. **Grade the final answer line, not the transcript.** Whole-text matching false-passed when the
   expected token (e.g. `CH3`) was quoted from the question's clues. Always parse the `ANSWER:` line.

5. **Token budget is part of correctness.** glm "failed" a problem it had actually solved because
   it was truncated before answering. Raising max_tokens changed its score. Report budget with results.

6. **Easy tests don't rank.** The first reasoning question was passed by everyone; only trap-laden,
   single-answer problems separated the models. Escalate difficulty until they diverge.

7. **Results vary run-to-run** (temperature + glm truncation). Treat single runs as samples; the
   *ordering* (gpt-oss ≫ qwen > glm > fmx on hard reasoning) is stable, the exact scores aren't.

## Operational gotchas
- **Cerebras 403:** default `urllib` User-Agent is blocked — send `User-Agent: curl/8`.
- **Cerebras models:** the key serves only `gpt-oss-120b` and `zai-glm-4.7`.
- **glm-4.7 truncation:** needs large `max_tokens` or it returns a reasoning trace, not an answer.
- **Ollama context:** the OpenAI-compat endpoint uses a default context (often ~4k). For long
  inputs use the native `/api/chat` with `options.num_ctx`, or bake `num_ctx` into the model.
- **fmx:** strip ```` ``` ```` fences from its output; it adds them even when told not to.
