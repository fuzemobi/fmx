# Model routing — using each MCP/model for the right purpose

How to route work across the on-device fmx model, the Cerebras API models, and local
Ollama models — by **capability, context, token budget, and cost**. Derived from the
benchmarks in this folder (see `FINDINGS.md`).

## Model profiles

| Model | Where | Context | Speed (rel.) | Cost /1M tok (in / out) | Sweet spot | Avoid for |
|-------|-------|---------|--------------|--------------------------|------------|-----------|
| **fmx** (Apple FM) | on-device (CLI / `fmx` MCP) | **~4k — small** | slow (20–60 s) | **$0** | summarize, classify, extract, quick math; private/offline | code, hard reasoning, long inputs |
| **gpt-oss-120b** | Cerebras API | ~128k | **fastest** (~1–2 s) | $0.25 / $0.69 | everything: code, reason, summarize, JSON | — (default pick) |
| **zai-glm-4.7** | Cerebras API | ~128k | slow + variable | $0.40 / $1.20 | hard reasoning *if* token-capped | uncapped use; cost-sensitive work |
| **qwen3-coder:30b** | Ollama (local) | up to 256k* | medium (~5–25 s) | **$0** | local code + general reasoning, private/offline | timezone/DST-type traps |

\* Ollama serves a *default* context (often ~4k) unless you raise it — see "Context discipline".

## Routing by task

| Task | First choice | Why / fallback |
|------|--------------|----------------|
| Write/edit code, tests, scripts | **gpt-oss-120b** | correct + fast + cheap. Local: qwen3-coder. **Never fmx.** |
| Summarize / rewrite prose | **gpt-oss-120b** (API) | fmx works if free/private matters (add anti-invention rule). **Not the cerebras-code MCP.** |
| Structured extraction → JSON | **gpt-oss-120b**, or **fmx** (`respond_schema`) | both reliable; fmx is fine here and free. |
| Hard multi-step reasoning | **gpt-oss-120b** | 4/4 consistently. glm only if you cap tokens; qwen local (misses DST-type traps). |
| Classify / route / label (cheap, bulk) | **fmx** or **qwen3-coder** | free; latency-tolerant. Escalate only if accuracy lags. |
| Anything private/offline/zero-cost | **fmx** (small) or **qwen3-coder** (capable) | size to the task; qwen for code/reasoning, fmx for short transforms. |
| Long document (> a few k tokens) | **gpt-oss-120b / glm** | fmx's ~4k context can't hold it; raise Ollama `num_ctx` if going local. |

## The `generate` router tool (preferred) — one tool, all backends, mode-gated

The `fmx` MCP server (`fmx mcp`) exposes a **`generate`** tool that encodes this whole
document as code. Call it instead of hand-routing:

```
generate(prompt, mode, model=None, backend=None, max_tokens=None)
mode ∈ {reasoning, summarization, code, extract}   # required
```

- **Backends:** fmx (on-device), Cerebras (gpt-oss-120b / zai-glm-4.7 via the OpenAI-compatible
  API at `https://api.cerebras.ai/v1`), Ollama (native `/api/chat`, `num_ctx` raised), and any
  other OpenAI-compatible endpoint via `FMX_OPENAI_BASE_URL` / `FMX_OPENAI_MODELS`.
- **Mode picks + validates the backend.** Defaults: code/reason/summarize → `gpt-oss-120b`,
  extract → `fmx`. The router **denies** unsupported (mode, model) pairs with a cited reason —
  e.g. `generate(mode="code", model="fmx")` → refused, "fmx fails at code… use gpt-oss-120b".
- **Discipline is baked in:** fence-stripping, anti-invention rule for summaries, an output cap
  for reasoning (and a forced cap on `zai-glm-4.7`, which runs away uncapped). Usage + cost are
  logged to stderr every call.
- **Context fitting, no lost context:** over-window `summarization` is **map-reduced**
  (chunk → summarize → reduce); over-window `reasoning`/`code` is **refused with an escalation
  suggestion** rather than truncated. `list_capabilities` returns the full matrix + availability.

The on-device-only tools (`respond`, `respond_schema`, `build_schema`) remain for direct fmx use.
The third-party **`cerebras-code` npm MCP is retired** — its single-tool, code-forcing wrapper is
exactly the bug FINDINGS.md caught (it can't summarize); use `generate(mode="code")` instead.

### Token discipline — three layers (RTK → headroom → generate)

These three don't call each other; they cover different stages of the token pipeline. None is a
substitute for another — `generate` fits what you *send*, the other two manage what you *hold*.

| Layer | Stage | Covers | How | Effort |
|-------|-------|--------|-----|--------|
| **RTK** | **inbound** — output entering your context | `git` / `pytest` / `grep` / `ls` / build logs | CLI filter, auto via Bash hook | automatic, $0, lossless-of-signal |
| **headroom** | **held** — arbitrary text already in your window | file Reads, API/MCP results, model outputs | MCP stash + `retrieve(hash)` | manual, **lossy**, fallback |
| **`generate` window-fitting** | **outbound** — prompt → backend model | fmx ~4k / cloud 128k / ollama `num_ctx` | `router.py` map-reduce / escalate | automatic |

```
shell commands ──RTK filters at source──► your context ──headroom (non-command blobs only)──► generate(...) ──► backend
                 (less junk ever enters)                 (lossy stash, last resort)            (fits to window)
```

**Lead with RTK** (`rtk init -g` — not installed yet). It's automatic and hits the biggest bloat
source — command output — losslessly. Reach for **headroom** only for arbitrary text RTK can't see
(a big `Read`, a non-command MCP result, a `generate` output), and prefer *not holding it* (`Grep`
over `Read`, `generate(mode="summarization")`) over its lossy stash. Neither touches `generate`:
a *backend* model can't call `headroom_retrieve` mid-generation, which is exactly why compression
stays agent-side — `generate` handles "input too big for this backend" itself (map-reduce /
escalate), never silent truncation.

## Token discipline
- **glm-4.7 must be token-capped.** Uncapped it over-reasons, costs up to ~$0.04 for a handful
  of questions, and often truncates before answering. Add "answer in ≤N tokens" and a hard
  `max_tokens`, or just use gpt-oss-120b.
- **Give reasoning models room, then cap.** Too small a budget truncates the answer (looks like a
  wrong answer); too large invites runaway cost. gpt-oss is concise; glm is not.
- **fmx is free but slow** — batch or background its calls; don't put it on a latency path.

## Context discipline
- **fmx ≈ 4k tokens.** Don't feed it whole files or long docs; summarize/chunk first, or route
  long context to a 128k cloud model.
- **Ollama defaults low.** The OpenAI-compat endpoint uses a default context (often ~4k) even for
  a 256k-capable model. For long inputs use the native `/api/chat` with `options.num_ctx`, or set
  `num_ctx` on the model (`ollama create`/Modelfile). Otherwise it silently truncates.
- **Cloud (128k)** is the safe home for long context.

## Cost discipline
- **Prefer $0 backends when they pass** the task: fmx for short transforms, qwen3-coder for
  local code/reasoning. Escalate to Cerebras only when local quality/latency is insufficient.
- **gpt-oss-120b is the cheap cloud** (~$0.25/$0.69) and usually the right escalation.
- **glm-4.7 is ~1.6–1.7× gpt-oss list price and far worse in practice** due to reasoning-token
  bloat — measured ~13–25× the effective cost per answered question. Avoid by default.
- **Always log token usage + cost with results** so routing decisions stay evidence-based.
