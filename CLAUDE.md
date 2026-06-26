# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`fmx` is a CLI wrapping Apple's on-device Foundation Model via `apple-fm-sdk`. Everything
runs on-device (no cloud, no API key) and only works on macOS 26+ with Apple silicon and
Apple Intelligence enabled. Four commands: `chat` (interactive REPL), `respond` (one-shot,
scriptable), `schema` (build a JSON Schema for structured output), `mcp` (serve the model as
MCP tools).

## Commands

```bash
uv sync                          # install deps + dev group
uv run fmx chat                  # run the CLI
uv run pytest                    # full suite; model tests auto-skip if no on-device model
uv run pytest tests/test_schema.py::test_name   # single test
uv run ruff check .              # lint (line-length 100, rules E/F/I/UP/B, B008 ignored)
uv build                         # build the package
uv run python benchmarks/run_battery.py   # capability matrix (fmx vs Cerebras vs Ollama)
```

The `mcp` extra (`mcp>=1.2`) is in the dev group, so `uv sync` pulls it in and the MCP
server is exercised by `uv run pytest`. End users install it separately: `uv pip install 'fmx[mcp]'`.

## Critical constraint: the SDK can't build off-device

`apple-fm-sdk` compiles C bindings against the macOS 26 Foundation Models framework, so it
**cannot be installed on CI or any non-eligible Mac**. This shapes everything:

- **Two test tiers.** SDK-free tests (schema parsing, CLI arg wiring) run anywhere. Tests
  needing the live model are marked `@pytest.mark.require_model` and auto-skip via
  `tests/conftest.py` when the model isn't available. When adding a test that touches the
  model, mark it `require_model`; keep pure logic (parsing, formatting) SDK-free so CI covers it.
- CI (`.github/workflows/ci.yml`) only lints, runs SDK-free tests, and builds. Full
  end-to-end coverage requires a macOS 26 (M1+) self-hosted runner.

## Architecture

The SDK touches everything except `schema.py`. Module layout reflects the command split:

- **`core.py`** — the single seam. `availability()` gates on the model and maps SDK
  unavailability reasons to actionable user messages; `make_session()` is the *only* place a
  session is created. The Private Cloud Compute / cloud backend will branch here once the SDK
  exposes it — keep session creation centralized so command modules never construct sessions directly.
- **`cli.py`** — Typer entry point (`fmx = "fmx.cli:app"`). Wires the three commands, runs
  the async command bodies via `asyncio.run`, and calls `_require_model()` before `chat`/`respond`.
  SDK/IO errors are caught and printed without a traceback (exit 1).
- **`chat.py`** — async REPL. Slash commands (`/save`, `/load`, `/clear`, `/system`, `/model`)
  are dispatched in `run_chat`; `/clear` and `/system` work by building a fresh session from
  `core.make_session`. Model errors during a turn are caught so the REPL stays alive.
- **`respond.py`** — one-shot generation to stdout. Handles three modes: structured
  (`--schema` → `session.respond(json_schema=...)`, printed via `GeneratedContent.to_json()`),
  streaming (`--stream`), and plain. Multimodal prompts become a `[text, ImageAttachment...]` list.
- **`schema.py`** — **SDK-free.** Parses `name:type[:description]` specs into JSON Schema.
  Note: Apple's on-device decoder requires `additionalProperties: false`, `x-order` (property
  ordering), and `title` beyond vanilla JSON Schema — `build_object_schema` always emits these.
  All fields are required. Raises `SchemaSpecError` on bad input.
- **`store.py`** — `/save` and `/load` round-trip a session through the SDK's transcript
  serialization (`session.transcript.to_dict()` / `Transcript.from_dict`). Instructions are
  embedded in the transcript and restored automatically; tool capabilities are not (chat is tool-free).
- **`mcp_server.py`** — `fmx mcp` exposes a `FastMCP` server. On-device tools (`respond`,
  `respond_schema`, `build_schema`) reuse the same seams (`core.make_session`,
  `respond.make_options`, `schema.build_schema`). Plus a **multi-backend router**: `generate`
  (and `list_capabilities`) route by task `mode` across fmx / Cerebras / Ollama / any
  OpenAI-compatible endpoint — see `router.py` + `backends.py`. SDK-bound imports are deferred
  *into the tool bodies* (and `router._call`'s apple branch) so the whole module imports cleanly
  on non-Apple machines — only the fmx-backed paths error at call time. Optional dependency
  (`mcp` extra); `cli.py:mcp_cmd` catches the missing import and prints an install hint.
- **`router.py` / `backends.py`** — the `generate` routing seam. `backends.py` (**SDK-free**) is
  the model registry + HTTP call layer (Cerebras/OpenAI-compatible via `/v1/chat/completions`;
  Ollama via native `/api/chat` with `num_ctx` to dodge the ~4k-truncation gotcha). `router.py`
  holds the mode × model capability matrix, per-mode discipline (fence-strip, anti-invention,
  reasoning output caps, forced cap on `zai-glm-4.7`), and context-window fitting — over-window
  summaries map-reduce, over-window reasoning/code refuse-and-escalate (never truncate). The
  matrix and lessons are lifted from `benchmarks/FINDINGS.md`; routing logic was promoted out of
  `benchmarks/harness.py`.

## Conventions

- Async throughout for model calls; `cli.py` is the sync↔async boundary.
- User-facing errors print clean messages via `rich` (no tracebacks); SDK availability
  problems route through `core.availability()`'s reason map.
- All modules use `from __future__ import annotations`.

## Benchmarks

`benchmarks/` answers the project's core question: when is the on-device model good enough vs.
when to escalate. It is **standalone** (not part of the package, not under `src/`) and grades
deterministically against answer keys — no eyeballing. Three backends, auto-skipped if absent:
`fmx` (the CLI, $0/offline), Cerebras HTTP (`CEREBRAS_API_KEY`), Ollama HTTP (local). The
routing conclusions live in `benchmarks/MODEL_ROUTING.md` and `benchmarks/FINDINGS.md`.

## Contributing gate

Every PR needs passing `lint-and-test` + CodeQL and one approving review. See `CONTRIBUTING.md`.
