"""MCP server exposing fmx's on-device model as tools (`fmx mcp`).

Reuses fmx's own seams — `core.make_session`, `respond.make_options`, and the
SDK-free `schema` builder — rather than re-touching apple-fm-sdk. The SDK-bound
imports are deferred into the tool bodies so this module (and `list_tools` plus
the SDK-free `build_schema` tool) import cleanly on machines without the SDK.
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from . import schema as schema_mod

mcp = FastMCP("fmx")


@mcp.tool()
async def respond(
    prompt: str,
    instructions: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """Generate one text response from the on-device model (mirrors `fmx respond`)."""
    from . import core
    from .respond import make_options

    ok, message = core.availability()
    if not ok:
        raise RuntimeError(message)
    session = core.make_session(instructions)
    options = make_options(temperature, max_tokens)
    return str(await session.respond(prompt, options=options))


@mcp.tool()
async def respond_schema(
    prompt: str,
    json_schema: dict,
    instructions: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """Generate structured output constrained to a JSON Schema; returns JSON text."""
    from . import core
    from .respond import make_options

    ok, message = core.availability()
    if not ok:
        raise RuntimeError(message)
    session = core.make_session(instructions)
    options = make_options(temperature, max_tokens)
    result = await session.respond(prompt, json_schema=json_schema, options=options)
    return result.to_json()


@mcp.tool()
def build_schema(fields: list[str], title: str | None = None) -> str:
    """Build a JSON Schema object from `name:type[:description]` specs (mirrors `fmx schema`).

    SDK-free — pair its output with `respond_schema` for structured generation.
    """
    return json.dumps(schema_mod.build_schema("object", fields, title=title), indent=2)


@mcp.tool()
async def generate(
    prompt: str,
    mode: str,
    model: str | None = None,
    backend: str | None = None,
    max_tokens: int | None = None,
) -> str:
    """Route generation by task mode across fmx / Cerebras / Ollama / OpenAI-compatible models.

    `mode` is required — one of: reasoning, summarization, code, extract. The router picks
    the right backend (default gpt-oss-120b on Cerebras for code/reason/summarize, fmx for
    extract), validates that the chosen model is trusted for the mode, and DENIES unsupported
    pairs with a reason (e.g. fmx + code). Bakes in per-mode discipline (fence-stripping,
    anti-invention for summaries, output caps for reasoning) and fits the input to the model's
    context window — escalating or map-reducing rather than truncating. Pass `model` (e.g.
    `qwen3-coder:30b`, `zai-glm-4.7`, `fmx`) and/or `backend` to override the default.
    """
    from .router import route

    return await route(prompt, mode, model, backend, max_tokens)


@mcp.tool()
def list_capabilities() -> str:
    """Show the mode × model capability matrix (which models serve which modes, + availability).

    SDK-free. Use it to decide which `model`/`mode` to pass to `generate`.
    """
    from .router import capabilities

    return json.dumps(capabilities(), indent=2)
