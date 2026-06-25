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
