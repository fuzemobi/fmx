# fmx benchmarks

Capability benchmarks that answer the question this project exists to answer:
**when is the on-device `fmx` model good enough, and when should you escalate to a cloud
or larger-local model?**

Three backends, four task types, all graded **deterministically** (no eyeballing):

| Backend | How | Cost | Notes |
|---------|-----|------|-------|
| `fmx` | `fmx respond` CLI (same on-device model the MCP `respond` tool calls) | $0 | private, offline, small context, slow |
| Cerebras | HTTP API — `gpt-oss-120b`, `zai-glm-4.7` | paid | needs `CEREBRAS_API_KEY` |
| Ollama | local HTTP API — e.g. `qwen3-coder:30b` | $0 | needs a running `ollama` |

## Layout

```
benchmarks/
├── harness.py          # backends (fmx CLI / Cerebras API / Ollama API) + graders + matrix
├── prompts.py          # the 4 task prompts + answer keys
├── run_battery.py      # capability matrix: summarize / code / reason / json
├── run_reasoning.py    # hard reasoning ranking (4 trap problems, scored 0–4)
├── data/sample_readme.md   # self-contained corpus for the summarization test
├── results/            # captured reports + raw model outputs
├── MODEL_ROUTING.md    # ← the decision guide: which model for what (context/token/cost)
└── FINDINGS.md         # ← ranking per model + everything we learned
```

## Run

```bash
# fmx must be on PATH; export CEREBRAS_API_KEY for cloud; have `ollama` running for local.
# Any missing backend is skipped automatically.
uv run python benchmarks/run_battery.py        # 4-category capability matrix
uv run python benchmarks/run_reasoning.py       # hard reasoning ranking
```

The Cerebras key is read from `CEREBRAS_API_KEY`/`CEREBRAS_APIKEY` (env or
`~/.secrets/api-keys.env`). The Ollama model defaults to `qwen3-coder:30b` — edit the
`OLLAMA_MODEL` constant in the runners to try another.

## The short answer

- **Code, summarize, extract, fast reasoning → `gpt-oss-120b` (Cerebras).** Best all-rounder:
  correct everywhere, fastest, cheapest cloud.
- **Free / private / offline general work → `qwen3-coder:30b` (Ollama).** Surprisingly strong
  reasoner for a code model; the right local default.
- **fmx (on-device) → summarize / classify / extract / quick math only. Never for code,
  never for long inputs, weak on hard multi-step reasoning.**
- **`glm-4.7` → avoid unless you cap its tokens.** It reasons fine but fails to terminate,
  burning a big budget (saw $0.04 for 4 questions) and often truncating before it answers.

Full detail and the numbers in **FINDINGS.md** and **MODEL_ROUTING.md**.
