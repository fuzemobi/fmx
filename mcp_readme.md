# Using the `fmx` MCP server with Claude Code

`fmx mcp` runs a [Model Context Protocol](https://modelcontextprotocol.io) server
over stdio that exposes Apple's **on-device** Foundation Model as tools. Once
registered, Claude Code can call the local model directly — useful for offloading
small reasoning/drafting steps to the on-device model, or just to watch how the
two models interact.

> Requires the same environment as `fmx` itself: **macOS 26+, Apple silicon (M1+),
> Apple Intelligence on**. The server runs locally; nothing leaves the device.

## Tools it exposes

| Tool | What it does |
| --- | --- |
| `respond` | One-shot text generation. Args: `prompt`, optional `instructions`, `temperature`, `max_tokens`. |
| `respond_schema` | Structured output constrained to a JSON Schema (`prompt` + `json_schema` → JSON text). |
| `build_schema` | Turn `name:type[:description]` specs into a JSON Schema (no model needed). |

## 1. Install the MCP extra

From the repo (development):

```bash
uv sync --extra mcp
```

Or, once installed as a tool:

```bash
uv pip install 'fmx[mcp]'   # or: pipx inject fmx mcp
```

Confirm the server starts (Ctrl-C to stop — it waits on stdio, so it'll just sit there):

```bash
uv run fmx mcp
```

## 2. Register it with Claude Code

Easiest — the `claude mcp add` CLI. Run this from **inside the repo** so the
relative `--directory` resolves:

```bash
claude mcp add fmx -- uv run --directory /Users/chadr/Projects/fmx fmx mcp
```

That writes a stdio server entry named `fmx`. To make it available in **every**
project rather than just this one, add `--scope user`:

```bash
claude mcp add fmx --scope user -- uv run --directory /Users/chadr/Projects/fmx fmx mcp
```

### Or edit the config by hand

`claude mcp add` just writes JSON. The equivalent entry (project `.mcp.json`, or
your user `~/.claude.json`) is:

```json
{
  "mcpServers": {
    "fmx": {
      "command": "uv",
      "args": ["run", "--directory", "/Users/chadr/Projects/fmx", "fmx", "mcp"]
    }
  }
}
```

If you installed `fmx` globally (`uv pip install 'fmx[mcp]'` / pipx), you can skip
`uv run` and point straight at the entry point:

```json
{
  "mcpServers": {
    "fmx": { "command": "fmx", "args": ["mcp"] }
  }
}
```

## 3. Verify and use it in Claude Code

```bash
claude mcp list          # should show: fmx
```

Inside a Claude Code session, `/mcp` lists connected servers and their tools —
look for `fmx` with `respond`, `respond_schema`, and `build_schema`.

Then just ask Claude to use it. Examples:

- *"Use the fmx `respond` tool to answer: explain async/await in one sentence."*
- *"Ask the on-device model (fmx respond) to write a Python function `add(a, b)`,
  then ask it again to rename `add` to `total`."* — the create-then-edit flow the
  test suite exercises.
- *"Use fmx `build_schema` to make a schema for `name:str age:int`, then call
  `respond_schema` with it to invent a person."*

Claude decides when to call the tools; you can also force it (*"call the fmx
respond tool with…"*). Watch the difference: Claude does the orchestration and
reasoning, while the small on-device model handles the delegated generation.

## Troubleshooting

- **Server won't start / `mcp` not installed** → `uv sync --extra mcp` (the `fmx mcp`
  command prints this hint too).
- **Tools error with "Apple Intelligence is turned off" / "Model not ready"** → the
  on-device model is gated; the error text says which condition failed. Enable
  Apple Intelligence in System Settings and retry.
- **`claude mcp list` shows fmx but tools don't appear** → run `uv run fmx mcp`
  manually; any import/SDK error surfaces there.
- **Heads-up on capability**: this is Apple's small on-device model. It's good at
  short generation and simple transforms (rename, add a parameter) but unreliable
  at more involved edits — let Claude own the hard reasoning and delegate the
  narrow bits.
